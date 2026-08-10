#!/usr/bin/env python3
"""Sandboxed command execution for the tool agent.

Runs a parsed argv list (never a shell string) against a granular policy and,
on Linux, inside a bubblewrap / docker sandbox, so that commands have no access
to the host home directory and (unless requested) the network.

Backends (selected in priority order):
  1. bubblewrap (``bwrap``)   -- strongest; packaged on every Linux distro
                                 (Gentoo: sys-apps/bubblewrap, Debian, Fedora, ...)
  2. docker ``run --rm``      -- portable fallback when bwrap is missing
  3. restricted               -- argv-only subprocess, NO namespace isolation.
                                 Only usable with an explicit opt-in.

Policy (``policy.toml``) classifies every command as one of:
  oracle       -- safe to auto-run, output returned
  interpreter  -- arbitrary code executors (python3 -c, node -e, sh -c, ...);
                  always require approval; combined with network => deny
  mutator      -- changes state; requires approval (remembered per session)
  deny         -- never run

API::

    policy = sandbox.load_policy("policy.toml")
    verdict = policy.classify(["python3", "-c", "print(1)"])
    result = sandbox.run([...], workspace="/path", network=False,
                         timeout_s=30, max_out=262144, approve=callable)

Result dict::

    {"exit_code": int, "stdout": str, "stderr": str,
     "duration": float, "truncated": bool, "backend": str}

stdlib-only.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    tomllib = None

ORACLE = "oracle"
INTERPRETER = "interpreter"
MUTATOR = "mutator"
DENY = "deny"

DEFAULT_TIMEOUT = 30
DEFAULT_MAX_OUT = 262144  # 256 KiB of captured output per stream
KILL_AFTER = 5            # SIGTERM then SIGKILL grace window

# system directories mounted read-only into the bwrap sandbox
SYSTEM_RO_DIRS = ["/usr", "/lib", "/lib64", "/bin", "/sbin", "/etc", "/opt"]
DOCKER_IMAGE = "python:3.13-slim"

_SECRET_BASENAMES = ("id_rsa", "id_dsa", "id_ecdsa", "id_ed25519")
_SECRET_SUFFIXES = (".pem", ".key", ".ppk")


class SandboxError(RuntimeError):
    """Raised when a command cannot be authorised or a backend is missing."""


@dataclass(frozen=True)
class Verdict:
    klass: str   # one of ORACLE / INTERPRETER / MUTATOR / DENY
    reason: str

    def __str__(self):
        return f"{self.klass}: {self.reason}"


def parse(text: str) -> list[str]:
    """Split a shell-style line into argv. Never uses a shell, so metacharacters
    (|, &&, ;, $(), backticks, >) are inert."""
    if not text or not text.strip():
        raise ValueError("empty command")
    pieces = shlex.split(text)
    if not pieces:
        raise ValueError("empty command")
    return pieces


def cmdline(argv: list[str]) -> str:
    return " ".join(shlex.quote(a) for a in argv)


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------
def _match_tokens(pattern: str, argv: list[str]) -> bool:
    """Prefix token match: 'git status' matches argv ['git','status','.']."""
    want = shlex.split(pattern)
    if len(want) > len(argv):
        return False
    return all(p == a for p, a in zip(want, argv))


def _tok_is_secret(tok: str) -> bool:
    if not tok or tok.startswith("-"):
        return False
    base = os.path.basename(tok.rstrip("/"))
    if base in _SECRET_BASENAMES:
        return True
    if base == ".env":
        return True
    if any(base.endswith(s) for s in _SECRET_SUFFIXES):
        return True
    if "credentials" in tok or "credential" in tok or ".ssh/" in tok:
        return True
    return False


class Policy:
    def __init__(self, oracle=(), interpreter=(), mutator=(), deny=(),
                 approved=None, source="policy.toml"):
        self.oracle = [str(p) for p in oracle]
        self.interpreter = [str(p) for p in interpreter]
        self.mutator = [str(p) for p in mutator]
        self.deny = [str(p) for p in deny]
        self.approved: dict[str, str] = dict(approved or {})
        self.source = source
        # longest first so specific rules win over catch-alls (e.g.
        # "python3 -c" beats "python3")
        self._oracle = sorted(self.oracle, key=len, reverse=True)
        self._interp = sorted(self.interpreter, key=len, reverse=True)
        self._mut = sorted(self.mutator, key=len, reverse=True)
        self._deny = sorted(self.deny, key=len, reverse=True)

    @staticmethod
    def from_dict(data: dict, source: str = "policy.toml") -> "Policy":
        def cmds(section: str) -> list[str]:
            node = data.get(section) or {}
            val = node.get("commands")
            if isinstance(val, list):
                return [str(x) for x in val]
            if isinstance(val, str):
                return [val]
            return []

        approved = data.get("approved_scripts") or {}
        pinmap: dict[str, str] = {}
        if isinstance(approved, dict):
            for path, dig in approved.items():
                if isinstance(dig, str) and (len(dig) in (40, 64, 128)):
                    pinmap[str(path)] = dig
        return Policy(cmds("oracle"), cmds("interpreter"), cmds("mutator"),
                      cmds("deny"), pinmap, source)

    def classify(self, argv: list[str]) -> Verdict:
        if not argv:
            return Verdict(DENY, "empty argv")

        for pattern in self._deny:
            if _match_tokens(pattern, argv):
                return Verdict(DENY, pattern)

        if any(_tok_is_secret(t) for t in argv):
            return Verdict(DENY, "secret file referenced on the command line")

        for pattern in self._interp:
            if _match_tokens(pattern, argv):
                pin = self._approved_script(argv)
                if pin is not None:
                    return pin
                return Verdict(INTERPRETER, pattern)

        for pattern in self._oracle:
            if _match_tokens(pattern, argv):
                return Verdict(ORACLE, pattern)

        for pattern in self._mut:
            if _match_tokens(pattern, argv):
                return Verdict(MUTATOR, pattern)

        return Verdict(MUTATOR, "unknown command (conservative default)")

    def _approved_script(self, argv: list[str]) -> Verdict | None:
        """python3 <pinned-script> auto-runs only when the file hash matches
        its pin in [approved_scripts]. Returns None when not applicable."""
        if len(argv) != 2:
            return None
        script = argv[1]
        path = Path(script)
        if not path.is_file():
            return None
        pin = self.approved.get(str(path)) or self.approved.get(path.name)
        if not pin:
            return None
        algo, _, want = pin.partition(":")
        if not want:
            want, algo = algo, "sha256"
        try:
            digest = hashlib.new(algo or "sha256", path.read_bytes()).hexdigest()
        except (OSError, ValueError):
            return None
        if digest.lower() == want.lower():
            return Verdict(ORACLE, f"approved script hash: {path}")
        return Verdict(DENY, f"approved script changed: {path}")

    def describe(self) -> list[str]:
        def fmt(name, items):
            shown = ", ".join(items[:10])
            if len(items) > 10:
                shown += " …"
            return f"{name:<7} ({len(items)}): {shown}"
        out = [fmt("oracle", self._oracle), fmt("interpreter", self._interp),
               fmt("mutator", self._mut), fmt("deny", self._deny)]
        if self.approved:
            out.append("approved_scripts ({0}): {1}".format(
                len(self.approved), ", ".join(list(self.approved)[:8])))
        return out


def load_policy(path: str = "policy.toml") -> Policy:
    if tomllib is None:
        raise SandboxError("policy needs Python >= 3.11 (tomllib)")
    p = Path(path)
    if not p.is_file():
        raise SandboxError(f"policy file not found: {p}")
    try:
        data = tomllib.loads(p.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise SandboxError(f"could not parse {p}: {e}")
    return Policy.from_dict(data, str(p))


def _auto_policy() -> Policy:
    """Load policy.toml from the working dir; fall back to safe defaults."""
    try:
        return load_policy("policy.toml")
    except SandboxError:
        return _STATIC_POLICY


# ---------------------------------------------------------------------------
# Backend detection & argv construction
# ---------------------------------------------------------------------------
def detect_backends() -> dict[str, str | None]:
    return {
        "bwrap": shutil.which("bwrap"),
        "docker": shutil.which("docker"),
    }


def install_hint() -> str:
    return (
        "install bubblewrap (Gentoo: `emerge sys-apps/bubblewrap`, "
        "Debian/Ubuntu: `apt install bubblewrap`, Fedora: `dnf install "
        "bubblewrap`, Arch: `pacman -S bubblewrap`) — or `docker` — or "
        "explicitly pass sandbox='restricted' to opt into the weak, "
        "argv-only fallback (no namespace isolation)."
    )


def select_backend(allow_restricted: bool = False) -> tuple[str, str | None]:
    found = detect_backends()
    if found["bwrap"]:
        return "bwrap", found["bwrap"]
    if found["docker"]:
        return "docker", found["docker"]
    if allow_restricted:
        return "restricted", None
    raise SandboxError(f"no sandbox available: {install_hint()}")


def _bwrap_argv(ws: str, network: bool, argv: list[str],
                workspace_ro: bool = False) -> list[str]:
    ro = []
    for d in SYSTEM_RO_DIRS:
        if os.path.isdir(d):
            ro += ["--ro-bind", d, d]
    args = (
        ["--new-session", "--die-with-parent",
         "--unshare-pid", "--unshare-uts", "--unshare-ipc"]
        + ro
        + ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    )
    if not network:
        args += ["--unshare-net"]
    bind = ["--ro-bind", ws, ws] if workspace_ro else ["--bind", ws, ws]
    args += bind + ["--chdir", ws, "--setenv", "HOME", ws, "--", *argv]
    return args


def _docker_argv(ws: str, network: bool, argv: list[str],
                 workspace_ro: bool = False) -> list[str]:
    net = "host" if network else "none"
    mount = (f"type=bind,source={ws},destination=/work,readonly"
             if workspace_ro else f"type=bind,source={ws},destination=/work")
    return [
        "run", "--rm", "--network", net,
        "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--tmpfs", "/tmp:size=128m,mode=1777",
        "--env", "HOME=/work", "--workdir", "/work",
        "--mount", mount,
        DOCKER_IMAGE, *argv,
    ]


def _git_hardened(argv: list[str]) -> list[str]:
    """Neutralise remote hooks before git commands run."""
    if argv and argv[0] == "git":
        return ["git", "-c", "core.hooksPath=/dev/null", *argv[1:]]
    return argv


def resolve(backend: str, exe: str | None, ws: str, network: bool,
            argv: list[str], workspace_ro: bool = False) -> list[str]:
    if backend == "bwrap":
        return [exe, *_bwrap_argv(ws, network, argv, workspace_ro)]
    if backend == "docker":
        return exe.split() + _docker_argv(ws, network, argv, workspace_ro)
    if backend == "restricted":
        return list(argv)
    raise SandboxError(f"unknown backend {backend!r}")


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------
def _read_limited(stream, cap: int) -> tuple[str, bool]:
    """Consume from a text stream up to ``cap`` bytes.

    Returns (text, truncated). Reading slightly beyond cap before stopping is
    fine; the caller must kill/close the stream afterwards to avoid deadlock.
    """
    chunks: list[str] = []
    size = 0
    truncated = False
    for line in iter(stream.readline, ""):
        size += len(line)
        if size > cap:
            chunks.append(line[: max(0, cap - (size - len(line)))])
            truncated = True
            break
        chunks.append(line)
    return "".join(chunks), truncated


def _kill_group(proc: subprocess.Popen):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        try:
            proc.kill()
        except OSError:
            pass
    except OSError:
        pass


def _pump(proc, cap: int):
    """Read stdout & stderr on separate threads bounded at ``cap``.

    If either stream hits the cap, the whole process group is killed at once —
    this stops an output-flooding (or exfil/DoS-styled) command from running on
    until the timeout instead of finishing promptly.

    Returns (out_text, err_text, truncated).
    """
    out_buf: list[str] = []
    err_buf: list[str] = []
    flags = {"out": False, "err": False}
    done = threading.Event()

    def reader(stream, buf, key):
        try:
            text, trunc = _read_limited(stream, cap)
            buf.append(text)
            flags[key] = trunc
            if trunc:
                _kill_group(proc)
        except (OSError, ValueError):
            pass
        finally:
            try:
                stream.close()
            except OSError:
                pass
            done.set()

    t1 = threading.Thread(target=reader, args=(proc.stdout, out_buf, "out"))
    t2 = threading.Thread(target=reader, args=(proc.stderr, err_buf, "err"))
    t1.start(); t2.start()
    done.wait()
    try:
        proc.wait(timeout=KILL_AFTER + 5)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        proc.wait()
    t1.join(); t2.join()
    return "".join(out_buf), "".join(err_buf), flags["out"] or flags["err"]


def run(argv: list[str], *, policy: Policy | None = None,
        workspace: str | Path | None = None, network: bool = False,
        timeout_s: int = DEFAULT_TIMEOUT, max_out: int = DEFAULT_MAX_OUT,
        backend: str | None = None, approve=None,
        workspace_ro: bool = False, env_whitelist: tuple[str, ...] = ()) -> dict:
    """Execute ``argv`` inside the sandbox.

    ``approve(verdict, argv) -> bool`` gates non-oracle commands. If it is
    None, only ORACLE commands run; anything else raises PermissionError.

    ``workspace_ro`` mounts the workspace read-only (bwrap ``--ro-bind`` /
    docker ``:ro``) — reads still work, writes fail inside the sandbox.

    The child always gets a sanitised environment: only HOME, a few LANG-ish
    keys, plus anything in ``env_whitelist`` (e.g. PATH-derivatives that the
    backend genuinely needs). Host secrets never reach the sandbox.
    """

    # ---- authorisation ---------------------------------------------------- #
    pol = policy if policy is not None else _auto_policy()
    verdict = pol.classify(argv)
    if verdict.klass == DENY:
        raise SandboxError(f"denied: {cmdline(argv)} ({verdict.reason})")

    if network and verdict.klass == INTERPRETER:
        raise SandboxError(
            "refusing network + interpreter (potential exfil channel): "
            f"{cmdline(argv)}")

    if verdict.klass == ORACLE:
        pass
    elif approve is None:
        raise PermissionError(
            f"approval required for {verdict.reason}: {cmdline(argv)}")
    elif not approve(verdict, argv):
        raise PermissionError(f"declined: {cmdline(argv)}")

    ws = str(Path(workspace or os.getcwd()).resolve())
    if not Path(ws).is_dir():
        raise SandboxError(f"workspace not a directory: {ws}")

    if backend is None:
        backend_name, exe = select_backend(allow_restricted=False)
    else:
        backend_name = backend
        exe = (shutil.which("bwrap") if backend == "bwrap"
               else shutil.which("docker") if backend == "docker" else None)
        if backend == "restricted":
            exe = None

    argv = _git_hardened(argv)
    inner = resolve(backend_name, exe, ws, network, argv, workspace_ro)
    full = ["timeout", "--foreground", "--kill-after=%d" % KILL_AFTER,
            str(timeout_s)] + inner

    # sanitised environment for the sandboxed child: never inherit host secrets
    safe_env = {
        "HOME": ws,
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "TERM": os.environ.get("TERM", "dumb"),
    }
    for key in env_whitelist:
        if key in os.environ:
            safe_env[key] = os.environ[key]

    started = time.monotonic()
    try:
        proc = subprocess.Popen(full, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                stdin=subprocess.DEVNULL,
                                text=True, bufsize=1,
                                env=safe_env,
                                start_new_session=True)
    except OSError as e:
        raise SandboxError(f"could not start sandbox: {e}")

    try:
        out, err, truncated = _pump(proc, max_out)
    except KeyboardInterrupt:
        _kill_group(proc)
        print()
        raise
    finally:
        pass

    return {
        "exit_code": proc.returncode,
        "stdout": out,
        "stderr": err,
        "duration": round(time.monotonic() - started, 3),
        "truncated": truncated,
        "backend": backend_name,
    }


# static fallback used when no policy.toml loads (safe defaults)
_STATIC_POLICY = Policy(
    oracle=("ls", "cat", "pwd", "grep", "find", "which", "wc", "head",
            "tail", "stat", "du", "df", "diff"),
    interpreter=("python3", "python", "node", "bash", "sh", "zsh", "perl",
                 "ruby", "php"),
    mutator=("git", "cp", "mv", "make", "pip", "npm", "curl", "wget"),
    deny=("sudo", "su", "chown", "chmod", "mkfs", "dd"),
    source="<static>",
)


def check(policy: str | None = None) -> dict:
    """Diagnostics for ``sandbox --check``."""
    found = detect_backends()
    mode, exe = select_backend(allow_restricted=True)
    report = {
        "backend": mode,
        "bwrap": bool(found["bwrap"]),
        "bwrap_path": found["bwrap"],
        "docker": bool(found["docker"]),
        "restricted": mode == "restricted",
        "network_default": "unshared",
    }
    if found["bwrap"]:
        try:
            r = subprocess.run(
                [found["bwrap"], "--ro-bind", "/", "/", "--unshare-net", "true"],
                capture_output=True, text=True, timeout=15)
            report["probe"] = "ok" if r.returncode == 0 else "failed"
            report["probe_detail"] = (r.stderr or r.stdout).strip()[:200]
        except Exception as e:  # noqa: BLE001
            report["probe"] = "failed"
            report["probe_error"] = str(e)
    if policy:
        try:
            p = load_policy(policy)
            report["policy"] = "ok"
            report["policy_details"] = p.describe()
        except SandboxError as e:
            report["policy"] = f"error: {e}"
    return report


def bootstrap() -> str:
    found = detect_backends()
    lines = ["sandbox bootstrap"]
    if found["bwrap"]:
        lines.append(f"  bwrap: OK ({found['bwrap']})")
    elif found["docker"]:
        lines.append(f"  docker: OK ({found['docker']}) — fallback backend")
    else:
        lines.append("  no sandbox executable found")
        lines.append("  " + install_hint())
    try:
        mode, exe = select_backend(allow_restricted=False)
        lines.append(f"  selected backend: {mode}")
    except SandboxError as e:
        lines.append(f"  {e}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(json.dumps(check(None), indent=2))