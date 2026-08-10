#!/usr/bin/env python3
"""Autonomous tool-agent loop: the model proposes commands, we run them inside
the sandbox, and the results are fed back until the model says ```done```.

Security model
--------------
* Commands come from the model reply, parsed as argv via ``sandbox.parse`` —
  never a shell string, so ``| && ; $( ) >`` are inert.
* Every command is classified by ``policy.toml``. The deny table is absolute in
  every tier; ``--net`` is never auto-approved; ``network + interpreter`` is
  denied outright (exfiltration channel).
* Approval tiers decide what auto-runs:
    oracle       -- auto: oracle + sha-pinned scripts;  prompt: mutator, int.
    mutator      -- auto: + mutators (git add/push, pip, rm, ...);
                    prompt: interpreters
    interpreter  -- auto: everything except deny (needs --allow-interpreters + a
                    loud double warning; you are giving the model shell power).
* Anything the model is not allowed to do is declined NON-destructively: the
  denial is fed back ("declined: ...") and the loop continues.
* ``--workspace-ro`` mounts the workspace read-only: reads work, writes fail
  inside the sandbox (recommended with the oracle tier).
* Result output cap (default 16 KiB) keeps the model's context bounded; the
  sandbox itself caps at `max_out`.
* Env is sanitised by ``sandbox.run``; stdin is /dev/null; ``killpg`` on
  Ctrl-C.

Model protocol (reply must contain ONE code block):
    ```sandbox
    <command line, single line>
    ```
      -> run that command in the sandbox (optionally first line ``--net``)
    ```done
    <summary>
    ```
      -> finish the task, print the summary
Anything else			  -> a hint is fed back and a step is spent.
"""

from __future__ import annotations

import os
import re
import shlex
import sys
import time
from pathlib import Path

import sandbox

ORACLE = "oracle"
INTERPRETER = "interpreter"
MUTATOR = "mutator"
DENY = "deny"

TIERS = ("oracle", "mutator", "interpreter")
DEFAULT_STEPS = 12
RESULT_CAP = 16384  # chars of command output fed back to the model

# redaction: values that must never be echoed to the model or written to logs
_REDACT_PATTERNS = [
    re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key|authorization"
               r"|bearer)\s*[:=]\s*\S+"),
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?"
               r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.S),
]
_REDACTED = "[REDACTED]"


class AgentError(RuntimeError):
    pass


def _redact(text: str) -> str:
    if not text:
        return text
    out = text
    for pat in _REDACT_PATTERNS:
        out = pat.sub(_REDACTED, out)
    return out


# --------------------------------------------------------------------------- #
# Protocol parsing
# --------------------------------------------------------------------------- #
_BLOCK_RE = re.compile(
    r"```(?:sandbox|run|done)\s*\n(.*?)```",
    re.S | re.I,
)


def parse_reply(reply: str):
    """Return ('sandbox', cmdline, net) | ('done', summary) | ('noise', text).

    ``net`` flags a leading ``--net`` line in the sandbox block request.
    """
    if not reply:
        return "noise", ""
    m = _BLOCK_RE.search(reply)
    if not m:
        return "noise", ""
    lang, _, _ = m.group(0)[3:m.group(0).find("\n")].partition("```")
    body = m.group(1).strip()
    kind = lang.strip().lower()
    if kind in ("done",):
        return "done", body
    # sandbox / run
    net = False
    lines = body.splitlines()
    if lines and lines[0].strip() in ("--net", "--net=true"):
        net = True
        body = "\n".join(lines[1:]).strip()
    return "sandbox", body, net


# --------------------------------------------------------------------------- #
# Approval gate
# --------------------------------------------------------------------------- #
def _gate(tier, verdict, network):
    """Pure policy gate for the agent loop.

    Returns True = auto-run, False = not auto (human decide / decline).
    deny is always False; network is never auto-approved; oracle always auto.
    """
    if verdict.klass == DENY:
        return False
    if network:
        return False
    if verdict.klass == ORACLE:
        return True
    if tier == "oracle":
        return False
    if tier == "mutator":
        return verdict.klass == MUTATOR
    return True  # tier == interpreter


def _make_approve(tier, interactive, network):
    """Per-iteration approve callback with network awareness baked in.

    - _gate(...) auto-approve -> run.
    - else if interactive + TTY -> one live y/N prompt.
    - else non-destructively decline (fed back to the model).
    """

    def approve(verdict, argv):
        if _gate(tier, verdict, network):
            return True
        if interactive and sys.stdin.isatty():
            line = sandbox.cmdline(argv)
            print(f"\n  [{verdict.klass}{' +net' if network else ''}] "
                  f"propose: {line}")
            while True:
                try:
                    ans = input("      allow? [y/N] ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print()
                    return False
                if ans in ("y", "yes"):
                    return True
                if ans in ("", "n", "no"):
                    return False
        return False

    return approve


# --------------------------------------------------------------------------- #
# Redaction + result formatting
# --------------------------------------------------------------------------- #
def _format_result(res: dict) -> str:
    out = (res.get("stdout") or "") + (res.get("stderr") or "")
    if not out.strip():
        out = "(no output)"
    out = _redact(out)
    if len(out) > RESULT_CAP:
        out = out[:RESULT_CAP] + "\n…[truncated]"
    tag = f"exit {res['exit_code']} [backend {res['backend']}]"
    if res.get("truncated"):
        tag += " [sandbox output truncated]"
    return f"### {tag}\n{out}"


# --------------------------------------------------------------------------- #
# The loop
# --------------------------------------------------------------------------- #
_SYSTEM = (
    "You are an autonomous coding agent. You may run commands to inspect or "
    "modify the workspace, but only through the sandbox protocol below.\n\n"
    "To run a command, reply with EXACTLY one fenced block:\n"
    "```sandbox\n<single-line command>\n```\n"
    "Add a first inner line `--net` only if you truly need network.\n\n"
    "When the task is complete, reply with:\n"
    "```done\n<brief summary of what you did>\n```\n\n"
    "Rules:\n"
    "- One code block per reply: either sandbox or done, not both.\n"
    "- The command may be DENIED by policy or DECLINED by the operator. If so, "
    "adapt: your environments grants may be limited.\n"
    "- Do not ask the operator for permission; just state what you would run.\n"
    "- Prefer read-only oracle commands (ls, cat, git status, ...) for "
    "inspection.\n"
    "- Workspace write access depends on the run configuration and may be "
    "read-only.\n"
)


def agent_loop(client, task: str, *, tier: str = ORACLE,
               workspace: str | None = None, workspace_ro: bool = False,
               max_steps: int = DEFAULT_STEPS, timeout_s: int = 30,
               max_out: int = sandbox.DEFAULT_MAX_OUT, backend: str | None = None,
               interactive: bool = True, allow_interpreters: bool = False,
               on_result=None, log_path: str | None = None) -> dict:
    """Run the agent loop until ```done``` or the step cap.

    ``client`` is any object with ``nonstream_chat(text) -> (text, usage, id)``
    that keeps conversation state across calls (e.g. qwen's QwenClient).

    ``on_result`` (optional) is called with (step_no, verdict_info, argv,
    formatted_output) so the REPL can print progress live.
    """
    if tier not in TIERS:
        raise AgentError(f"unknown tier {tier!r}; choose from {TIERS}")
    if tier == INTERPRETER and not allow_interpreters:
        raise AgentError(
            "--tier interpreter requires --allow-interpreters. Interpreter tier "
            "gives the model arbitrary code execution inside the sandbox; "
            "re-read policy.toml before enabling it.")

    ws = str(Path(workspace or os.getcwd()).resolve())
    if not Path(ws).is_dir():
        raise AgentError(f"workspace not a directory: {ws}")

    steps = 0
    history: list[dict] = []
    started = time.monotonic()
    header = f"# Agent run — {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n" \
             f"- tier: {tier}\n- workspace_ro: {workspace_ro}\n" \
             f"- workspace: {ws}\n\n## Task\n{task}\n\n"

    def _log_entry(role, text):
        history.append({"role": role, "content": _redact(text)})

    _log_entry("user", f"## Task\n{task}")
    msg = _SYSTEM + f"\n\n## Task\n{task}\n\nFirst, inspect the workspace: " \
                    f"{ws}. Then complete the task. Reply with a sandbox or " \
                    f"done block."
    reply, usage, cid = _call(client, msg)
    _log_entry("assistant", reply)

    while steps < max_steps:
        steps += 1
        kind = parse_reply(reply)[0]

        if kind == "done":
            summary = parse_reply(reply)[1]
            dur = round(time.monotonic() - started, 1)
            res = {
                "status": "done", "steps": steps - 1,
                "summary": _redact(summary), "duration": dur,
                "chat_id": cid, "usage": usage or {},
            }
            _log_entry("user", "```done```")
            _write_log(log_path, header, history, res)
            return res

        if kind == "noise":
            feedback = ("[hint] Your reply had no sandbox/done code block. "
                        "Reply with exactly one block: "
                        "```sandbox\n<command>\n``` or "
                        "```done\n<summary>\n```")
            _log_entry("user", feedback)
            reply, usage, cid = _call(client, feedback)
            _log_entry("assistant", reply)
            continue

        # kind == "sandbox"
        _cmdline, net_flag = parse_reply(reply)[1], parse_reply(reply)[2]
        try:
            argv = sandbox.parse(_cmdline)
        except ValueError as e:
            feedback = f"[parse error] {e}"
            _log_entry("user", feedback)
            reply, usage, cid = _call(client, feedback)
            _log_entry("assistant", reply)
            continue

        np_line = sandbox.cmdline(argv)
        approve = _make_approve(tier, interactive, net_flag)
        try:
            res = sandbox.run(argv, workspace=ws, network=net_flag,
                              timeout_s=timeout_s, max_out=max_out,
                              workspace_ro=workspace_ro, backend=backend,
                              approve=approve)
            verdict_desc = "ran"
            feedback = _format_result(res)
        except sandbox.SandboxError as e:
            verdict_desc = "denied-by-policy"
            feedback = f"[denied] {e}"
        except PermissionError as e:
            verdict_desc = "declined"
            feedback = f"[declined] {e}"

        if on_result is not None:
            on_result(steps, verdict_desc, argv, feedback)

        _log_entry("user", f"[{verdict_desc}] {np_line}\n{feedback}")
        reply, usage, cid = _call(client, feedback)
        _log_entry("assistant", reply)

    dur = round(time.monotonic() - started, 1)
    res = {"status": "step-cap", "steps": max_steps, "summary": None,
           "duration": dur, "chat_id": cid, "usage": usage or {}}
    _write_log(log_path, header, history, res)
    return res


def _call(client, text):
    """Single model call returning (text, usage, chat_id)."""
    return client.nonstream_chat(text)


def _write_log(log_path, header, history, res):
    if not log_path:
        return
    try:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        body = [header]
        for h in history:
            role = h["role"]
            body.append("\n### " + ("USER" if role == "user" else "ASSISTANT"))
            body.append(h["content"])
        body.append("\n## Result\n" + str(res))
        Path(log_path).write_text("\n".join(body), encoding="utf-8")
    except OSError as e:
        print(f"[agent] could not write log {log_path}: {e}", file=sys.stderr)