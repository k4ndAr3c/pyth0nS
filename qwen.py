#!/usr/bin/env python3
"""
qwen.py - Terminal client for chat.qwen.ai (Qwen Chat).

A self-contained CLI that talks directly to the Qwen Chat web backend:
  * login with email/password or a browser-extracted JWT token
  * persistent multi-turn conversations (kept on the server)
  * streaming responses, token / quota usage, account status
  * file uploads, model switching, conversation history management

Uses only the `requests` and `rich` libraries (both already installed).

Usage:
  qwen.py login [--token JWT | --email E --password P]
  qwen.py chat                 # interactive REPL (the default)
  qwen.py chat -c              # resume the most recent conversation
  qwen.py -c                   # same, with the default REPL
  qwen.py ask "your question"  # one-shot question
  qwen.py ask "?" --reasoning thinking   # force deep reasoning
  qwen.py status               # account, model, quota + tokens used
  qwen.py models               # list available models
  qwen.py history              # list saved conversations
  qwen.py new                  # start a fresh conversation
  qwen.py use <chat_id>        # resume a saved conversation
  qwen.py del <chat_id>        # delete a saved conversation
  qwen.py token                # show the stored token (masked)
  qwen.py logout
  qwen.py ds [ask|chat|models|history|sync|new|use|view|print|del]
                               # DeepSeek via local Deepseek-API proxy
                               #   (git clone Deepseek-API && python app.py)

Interactive REPL commands:
  /help           show help
  /model <name>   switch model
  /upload <path>  attach a file (repeatable)
  /files          list files attached to this session
  /clearfiles     drop all attached files
  /new            start a new conversation
  /status         show quota + tokens used so far
  /reason [auto|thinking|fast] reasoning mode (no arg cycles)
  /history        list saved conversations
  /grep <pattern> [ids...] [-n N | -a] search conversations (default: all)
  /use <id>       resume a saved conversation
  /rename <title> rename the current conversation
  /del <id>... [-n N] [-f] delete conversations (ids or the N most recent)
  /save <path>    save transcript to a file (.md) — /save <id> [path] exports a stored chat
  /token          show stored token (masked)
  /exit           quit
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from getpass import getpass
from pathlib import Path

import requests
import subprocess

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

try:
    import deepseek_client
except ImportError:
    deepseek_client = None

try:
    import sandbox
except ImportError:
    sandbox = None

try:
    import agent as agent_mod
except ImportError:
    agent_mod = None

BASE_URL = os.environ.get("QWEN_BASE_URL", "https://chat.qwen.ai")
API = f"{BASE_URL}/api"
CONFIG_DIR = Path(os.environ.get("QWEN_CONFIG_DIR", Path.home() / ".config" / "qwen-cli"))
CONFIG_FILE = CONFIG_DIR / "config.json"

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

SESSION_KEY = "cache_session_id"
DEFAULT_MODEL = os.environ.get("QWEN_MODEL", "qwen3.8-max")


# --------------------------------------------------------------------------- #
# Terminal helpers (rich if available, plain fallback)
# --------------------------------------------------------------------------- #
try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich import box

    _console = Console(highlight=False)
    _RICH = True
except ImportError:
    _RICH = False

    class _Console:
        def print(self, *a, **k):
            text = " ".join(str(x) for x in a)
            sys.stdout.write(text + "\n")

        def out(self, text=""):
            sys.stdout.write(str(text))

    _console = _Console()


def cprint(*args, **kwargs):
    _console.print(*args, **kwargs)


def emsg(msg):
    cprint(f"[red]✗ {msg}[/red]" if _RICH else f"✗ {msg}")


def okmsg(msg):
    cprint(f"[green]✓ {msg}[/green]" if _RICH else f"✓ {msg}")


def warn(msg):
    cprint(f"[yellow]! {msg}[/yellow]" if _RICH else f"! {msg}")


def dim(msg):
    cprint(f"[dim]{msg}[/dim]" if _RICH else msg)


def _stream_write(piece):
    # rich's Console.out() emits a fresh line per call — wrong for streaming
    # deltas (would stack every token on its own line). Write raw instead so
    # the terminal wraps the answer naturally at word boundaries.
    try:
        sys.stdout.write(str(piece))
        sys.stdout.flush()
    except Exception:
        pass


def _make_reason_writer():
    """Return an `on_reason` callback that prints the thinking trace dimmed,
    with a one-time header per response (fresh state per call)."""
    state = {"header": False}

    def _w(piece):
        try:
            if not state["header"]:
                state["header"] = True
                dim("reasoning")
            sys.stdout.write(str(piece))
            sys.stdout.flush()
        except Exception:
            pass

    return _w


def init_readline():
    """Enable interactive line editing + persistent up/down history."""
    try:
        import readline
        import atexit
    except ImportError:
        return
    hist = CONFIG_DIR / "history"
    try:
        readline.set_history_length(1000)
        if hist.exists():
            readline.read_history_file(str(hist))
    except Exception:
        pass

    def _save():
        try:
            readline.write_history_file(str(hist))
        except Exception:
            pass

    atexit.register(_save)

    _SLASH_COMMANDS = [
        "help", "model", "models", "upload", "files", "clearfiles", "new",
        "status", "history", "use", "view", "print", "download", "rename",
        "del", "save", "token", "exit", "quit", "think", "search", "multi",
        "show", "run", "reason", "grep",
    ]

    def _complete(text, state):
        """Tab-complete: '/' + command names; for /upload complete file paths."""
        try:
            line = readline.get_line_buffer()
        except Exception:
            return None
        stripped = line.lstrip()
        # Not a slash command -> fall back to path completion.
        if line != stripped or stripped[:1] != "/":
            return _path_complete(text, state)
        cmdline = stripped[1:]
        part, _, _ = cmdline.partition(" ")
        if " " not in cmdline:
            # no space yet: candidate is the command itself
            probe = text.lstrip("/")
            matches = [f"/{c}" for c in _SLASH_COMMANDS
                       if c.startswith(probe.lower())]
            try:
                return matches[state]
            except IndexError:
                return None
        cmd = part.lower()
        after = cmdline[len(part) + 1:]
        if cmd == "upload":
            return _path_complete(after, state)
        return None

    try:
        readline.set_completer(_complete)
        readline.set_completer_delims(" \t\n")
        # Bind Tab to completion even if ~/.inputrc or the terminal binds it
        # to something else (space-insertion etc.). Without this the
        # completer is never invoked and slash-command TAB stops working.
        readline.parse_and_bind("tab: complete")
    except Exception:
        pass


def _path_complete(text, state):
    """Complete a partial filesystem path with readline's filename generator."""
    try:
        import glob
        text = os.path.expanduser(text or "")
        dirname, _, _ = text.rpartition("/")
        if not dirname:
            pattern = text + "*"
            hits = set(glob.glob(pattern)) | set(glob.glob(pattern + "/"))
        else:
            dirname = dirname + "/"
            full = dirname + "*"
            hits = set(glob.glob(full)) | set(glob.glob(full + "/"))
        results = []
        for h in sorted(hits):
            h = h.rstrip("/")
            if os.path.isdir(h):
                results.append(h + "/")
            else:
                results.append(h + " ")
        try:
            return results[state]
        except IndexError:
            return None
    except Exception:
        return None


def markdown(text):
    if _RICH:
        _console.print(Markdown(text))
    else:
        print(text)


def panel(title, text):
    if _RICH:
        _console.print(Panel(text, title=title, border_style="cyan", expand=False))
    else:
        print(f"== {title} ==\n{text}")


def _has_display() -> bool:
    if sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def ask_yes_no(prompt, default=True):
    suffix = " [Y/n]" if default else " [y/N]"
    while True:
        try:
            ans = input(prompt + suffix + " ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return default
        if not ans:
            return default
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False


# --------------------------------------------------------------------------- #
# Config / token storage
# --------------------------------------------------------------------------- #
def _load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    tmp.replace(CONFIG_FILE)
    os.chmod(CONFIG_FILE, 0o600)


def get_token() -> str:
    return _load_config().get("token", "")


def get_cookies() -> list:
    return _load_config().get("cookies", []) or []


def has_cookies() -> bool:
    return bool(get_cookies())


def set_token(token: str) -> None:
    cfg = _load_config()
    cfg["token"] = token
    _save_config(cfg)


def save_session(token: str, cookies: list) -> None:
    cfg = _load_config()
    cfg["token"] = token
    cfg["cookies"] = cookies
    _save_config(cfg)


def save_capture(cap: dict) -> None:
    cfg = _load_config()
    cfg["chat_capture"] = cap
    _save_config(cfg)


def get_capture() -> dict:
    return _load_config().get("chat_capture", {}) or {}


def _cookie_host() -> str:
    from urllib.parse import urlparse
    try:
        return urlparse(BASE_URL).netloc
    except Exception:
        return "chat.qwen.ai"


def parse_cookie_str(text: str) -> list:
    """Parse a Cookie header string (`a=1; b=2`) into stored-cookie dicts
    bound to chat.qwen.ai. Used for headless login (`--cookie`)."""
    host = _cookie_host()
    out: list = []
    if host.startswith("www."):
        domain = "." + host[4:]
    elif host.count(".") >= 2:
        domain = "." + host
    else:
        domain = "." + host
    for part in text.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, val = part.partition("=")
        name = name.strip()
        val = val.strip()
        if not name:
            continue
        out.append({"name": name, "value": val, "domain": domain, "path": "/"})
    return out


def token_from_cookies(cookies: list) -> str:
    for c in cookies or []:
        if c.get("name") == "token":
            return c.get("value", "")
    return ""


def clear_token() -> None:
    cfg = _load_config()
    cfg.pop("token", None)
    cfg.pop("cookies", None)
    _save_config(cfg)


def mask_token(token: str) -> str:
    if not token:
        return "<none>"
    if len(token) <= 20:
        return token[:4] + "…"
    return f"{token[:16]}…{token[-6:]}"


# --------------------------------------------------------------------------- #
# HTTP client
# --------------------------------------------------------------------------- #
class QwenError(Exception):
    pass


class _StopStream(Exception):
    pass


class QwenClient:
    def __init__(self, token: str | None = None):
        self.token = token or get_token()
        self.session = requests.Session()
        self.session.verify = True
        self._load_cookies()
        self._chat_id: str | None = None
        self._parent_id: str | None = None
        # Thread this session was forked from (web search / upload can make
        # chat.qwen.ai spawn a new thread and reply there). Lets the REPL
        # reconnect to the old thread (`/parent`), like the web UI's arrows.
        self._parent_chat_id: str | None = None
        self.attachments: list[dict] = []          # uploaded file references
        self.tokens_used = 0                       # cumulative tokens this run
        self.model = DEFAULT_MODEL
        # Reasoning behaviour: "auto" (server default), "thinking" (force
        # deep reasoning), "fast" (skip reasoning). Mirrors the web UI's
        # Auto / Thinking / Fast selector.
        self.reasoning = os.environ.get("QWEN_REASONING", "auto").lower()
        if self.reasoning not in ("auto", "thinking", "fast"):
            self.reasoning = "auto"

    def _thinking_flag(self):
        """Map the reasoning mode to the API's `enable_thinking` (True/False);
        `auto` returns None so the server/model picks the default."""
        if self.reasoning == "thinking":
            return True
        if self.reasoning == "fast":
            return False
        return None

    def _load_cookies(self) -> None:
        # chat.qwen.ai gates streaming behind browser anti-bot cookies; replay
        # the ones captured by the Playwright login (see login_with_browser).
        jar = self.session.cookies
        for c in get_cookies():
            try:
                jar.set(
                    c.get("name", ""), c.get("value", ""),
                    domain=c.get("domain"), path=c.get("path", "/"),
                )
            except Exception:
                continue

    # -- headers ---------------------------------------------------------- #
    def _headers(self, streaming=False, extra=None):
        h = {
            "Accept": "text/event-stream" if streaming else "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": UA,
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/",
            "X-Request-Id": str(uuid.uuid4()),
            "source": "web",
            "device_type": "web",
            "Timezone": "UTC",
        }
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if extra:
            h.update(extra)
        return h

    # -- low level -------------------------------------------------------- #
    def _request(self, method, path, *, base=None, params=None, json=None,
                 data=None, files=None, stream=False, extra=None, retries=3):
        url = f"{base or API}{path}"
        for attempt in range(retries):
            try:
                r = self.session.request(
                    method, url, params=params, json=json, data=data,
                    files=files, headers=self._headers(streaming=stream, extra=extra),
                    stream=stream, timeout=(10, 300) if stream else 30,
                )
            except requests.exceptions.RequestException as e:
                if attempt < retries - 1:
                    time.sleep(1.5 * (2 ** attempt))
                    continue
                raise QwenError(f"Network error: {e}") from e

            if r.status_code == 401:
                raise QwenError("Authentication failed (401). Token invalid/expired — run `qwen.py login`.")
            if r.status_code == 403:
                raise QwenError("Access forbidden (403). Token may be expired or flagged.")
            if r.status_code == 429:
                raise QwenError("Rate limited (429). Slow down and retry later.")
            if r.status_code >= 500:
                if attempt < retries - 1:
                    time.sleep(1.5 * (2 ** attempt))
                    continue
                raise QwenError(f"Server error ({r.status_code}).")
            r.raise_for_status()
            return r
        raise QwenError("Request failed after retries.")

    # -- auth ------------------------------------------------------------- #
    def signin(self, email, password):
        # Current web app (qwen-chat-fe) posts a single-round SHA-256 hex digest
        # of the password to the v2 signin endpoint; v1 signin is retired (400).
        import hashlib
        pwd_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        r = self._request("POST", "/v2/auths/signin", base=API,
                          json={"email": email, "password": pwd_hash})
        data = r.json()
        if not data.get("success"):
            details = ((data.get("data") or {}).get("details")
                       or (data.get("data") or {}).get("code")
                       or (data.get("data") or {}).get("message")
                       or "Login failed")
            raise QwenError(f"Login failed: {details}")
        payload = data.get("data") or {}
        token = payload.get("token", "")
        # The JWT lives on the /auths/ profile endpoint; fetch it if signin
        # didn't return one directly.
        if not token:
            try:
                who = self.whoami()
                token = who.get("token") or ""
            except QwenError:
                token = ""
        if not token and "token=" in r.headers.get("set-cookie", ""):
            token = r.headers["set-cookie"].split("token=")[1].split(";")[0]
        if not token:
            raise QwenError("Login succeeded but no token was returned.")
        self.token = token
        set_token(token)
        return token

    def whoami(self):
        r = self._request("GET", "/v1/auths/", base=API)
        data = r.json()
        if isinstance(data, dict) and "data" in data and "id" not in data:
            return data.get("data", {})
        return data

    # -- chat ------------------------------------------------------------- #
    def _build_messages(self, user_text, structured=None):
        msgs = []
        files = []
        for a in self.attachments:
            fid = a["file_id"]
            files.append({
                "type": "file", "name": a.get("name", ""),
                "file_type": "application/octet-stream", "showType": "file",
                "file_class": "document", "status": "uploaded",
                "url": a.get("url") or f"{API}/v1/files/{fid}/content",
                "file_id": fid,
            })
        if structured or files:
            msgs.append({"role": "user", "content": user_text, "files": files})
        else:
            msgs.append({"role": "user", "content": user_text})
        return msgs

    def _chat_spec(self):
        cap = get_capture()
        if cap and cap.get("body"):
            return cap
        return None

    def _new_msg(self, user_text, template):
        """Build a user message matching the shape the web app sends, so the
        server accepts it (bare OpenAI messages are rejected -> blank reply)."""
        ft = {}
        feature_config = None
        if isinstance(template, dict):
            feature_config = template.get("feature_config")
            for k in ("id", "fid", "files", "user_action",
                      "chat_type", "sub_chat_type", "feature_extra",
                      "extra", "meta"):
                if k in template:
                    ft[k] = template[k]
        now = int(time.time())
        content = user_text
        files = []
        for a in self.attachments:
            fid = a["file_id"]
            files.append({
                "type": "file",
                "name": a.get("name", ""),
                "file_type": "application/octet-stream",
                "showType": "file",
                "file_class": "document",
                "status": "uploaded",
                "url": a.get("url") or f"{API}/v1/files/{fid}/content",
                "file_id": fid,
            })
        vision = any(
            (a.get("file_class") in ("vision", "image", "video"))
            or (a.get("name", "").lower().endswith((".png", ".jpg", ".jpeg",
                                                    ".webp", ".gif", ".mp4",
                                                    ".mov", ".avi")))
            for a in self.attachments
        )
        ft.update({
            "id": None,
            "fid": str(uuid.uuid4()),
            "parentId": self._parent_id,
            "parent_id": self._parent_id,
            "childrenIds": [],
            "role": "user",
            "user_action": "chat",
            "content": content,
            "files": files or [],
            "timestamp": now,
            "models": [self.model],
            "model": "",
            "chat_type": "v2t" if vision else "t2t",
        })
        if feature_config is not None:
            ft["feature_config"] = feature_config
        ft.setdefault("extra", {"meta": {"subChatType": ft["chat_type"]}})
        ft.setdefault("sub_chat_type", ft["chat_type"])
        return ft

    def chat_once(self, user_text, stream=True):
        cap = self._chat_spec()
        body = {
            "model": self.model,
            "messages": self._build_messages(user_text),
            "stream": stream,
        }
        if self._chat_id:
            body["chat_id"] = self._chat_id

        if cap:
            body = json.loads(json.dumps(cap.get("body") or {}))
            if not self._chat_id:
                self.create_chat()
            tmpl = {}
            for m in body.get("messages") or []:
                if isinstance(m, dict) and m.get("role") == "user":
                    tmpl = m
                    break
            body["messages"] = [self._new_msg(user_text, tmpl)]
            body["model"] = self.model
            body["chatId"] = self._chat_id
            body["chat_id"] = self._chat_id
            body["parentId"] = self._parent_id or ""
            body["parent_id"] = self._parent_id or None
            body["stream"] = bool(stream)
            if "timestamp" in body:
                body["timestamp"] = int(time.time())
            enable = self._thinking_flag()
            if enable is not None:
                msg = body["messages"][0]
                fc = msg.get("feature_config")
                if not isinstance(fc, dict):
                    fc = {}
                    msg["feature_config"] = fc
                fc["thinking_enabled"] = enable
                body["enable_thinking"] = enable
            return body
        enable = self._thinking_flag()
        if enable is not None:
            body["enable_thinking"] = enable
        return body

    def _adopt_chat_id(self, chat_id):
        """Adopt `chat_id` as the current thread, remembering the previous one
        when the server forked us onto a new thread (web search / upload can
        spawn one). The remembered id lets the REPL reconnect via `/parent`."""
        if self._chat_id and chat_id and chat_id != self._chat_id:
            self._parent_chat_id = self._chat_id
        self._chat_id = chat_id

    def stream_chat(self, user_text, on_delta=None, on_reason=None):
        """Stream a completion, returning (full_text, usage, chat_id).

        `on_delta` receives answer content; when reasoning is enabled, the
        model's thinking trace arrives in `phase == "think"` deltas and is
        routed to `on_reason` instead of being mixed into the answer."""
        cap = self._chat_spec()
        body = self.chat_once(user_text, stream=True)
        if cap:
            r = self._req_or_capture(cap, body, stream=True)
        else:
            r = self._request("POST", "/v2/chat/completions", json=body, stream=True,
                              extra={"X-Accel-Buffering": "no", "Accept": "text/event-stream"})
        full = []
        usage = {}
        chat_id = self._chat_id
        error = None
        try:
            for raw in r.iter_lines(decode_unicode=True):
                if not raw:
                    continue
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                line = raw.strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    evt = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if isinstance(evt, dict):
                    if "response.created" in evt:
                        rc = evt["response.created"]
                        if isinstance(rc, dict):
                            if rc.get("chat_id"):
                                chat_id = rc["chat_id"]
                            if rc.get("parent_id"):
                                self._parent_id = rc["parent_id"]
                            if rc.get("response_id"):
                                self._parent_id = self._parent_id or rc["response_id"]
                    if evt.get("chat_id"):
                        chat_id = evt["chat_id"]
                    # Surface anti-bot / server errors instead of a blank line.
                    ret = evt.get("ret")
                    if isinstance(ret, list) or isinstance(ret, str):
                        code = ret[0] if isinstance(ret, list) else ret
                        if isinstance(code, str) and (code.startswith("FAIL") or "VALIDATE" in code):
                            error = f"Server rejected chat: {code} {' '.join(ret[1:]) if isinstance(ret, list) else ''}".strip()
                            raise _StopStream()
                    msg = evt.get("message") or {}
                    if isinstance(msg, dict):
                        msg_id = msg.get("id") or msg.get("message_id")
                        par = msg.get("parent_id")
                        if msg_id and par:
                            self._parent_id = msg_id
                    if evt.get("usage"):
                        usage = evt["usage"]
                    piece = None
                    reason = False
                    for ch in evt.get("choices") or []:
                        delta = (ch.get("delta") or {})
                        if delta.get("phase") == "think" or delta.get("reasoning_content") is not None:
                            piece = (delta.get("content")
                                     or delta.get("reasoning_content") or None)
                            reason = True
                            break
                        piece = delta.get("content") or None
                        if piece:
                            break
                    if piece is None and isinstance(msg, dict):
                        piece = (msg.get("content_delta")
                                 or msg.get("content")
                                 or msg.get("delta") or None)
                    if piece is None:
                        piece = evt.get("content") or evt.get("text") or None
                    if isinstance(piece, str) and piece:
                        if reason:
                            if on_reason:
                                on_reason(piece)
                        else:
                            full.append(piece)
                            if on_delta:
                                on_delta(piece)
        except _StopStream:
            pass
        finally:
            r.close()
        if error:
            raise QwenError(error)
        if chat_id:
            self._adopt_chat_id(chat_id)
        self._note_usage(usage)
        return "".join(full), usage, chat_id

    def nonstream_chat(self, user_text):
        cap = self._chat_spec()
        body = self.chat_once(user_text, stream=False)
        if cap:
            r = self._req_or_capture(cap, body, stream=False)
        else:
            r = self._request("POST", "/v2/chat/completions", json=body)
        data = r.json().get("data", r.json())
        chat_id = data.get("chat_id") or self._chat_id
        if chat_id:
            self._adopt_chat_id(chat_id)
        text = ""
        usage = {}
        if data.get("usage"):
            usage = data["usage"]
        for ch in data.get("choices") or []:
            msg = (ch.get("message") or {})
            text += msg.get("content") or ""
        self._note_usage(usage)
        return text, usage, chat_id

    def _req_or_capture(self, cap, body, *, stream):
        from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
        base = cap.get("url") or f"{API}/v2/chat/completions"
        # Reset the captured URL's chat_id: fresh chats must not reuse the test
        # conversation's id, and resumed chats should point at the live one.
        parsed = urlparse(base)
        q = dict(parse_qsl(parsed.query))
        q.pop("chat_id", None)
        if self._chat_id:
            q["chat_id"] = self._chat_id
        url = urlunparse(parsed._replace(query=urlencode(q)))
        method = cap.get("method", "POST")
        h = self._headers(streaming=stream)
        for k, v in (cap.get("headers") or {}).items():
            if k.lower() in ("content-length", "host", "connection"):
                continue
            h.setdefault(k, v)
        r = self.session.request(method, url, json=body, headers=h, stream=stream,
                                 timeout=(10, 300) if stream else 60)
        if not r.ok:
            snippet = ""
            try:
                snippet = r.text[:300]
            except Exception:
                pass
            raise QwenError(f"Chat request failed ({r.status_code}): {snippet}")
        return r

    def _note_usage(self, usage):
        if not usage:
            return
        total = usage.get("total_tokens")
        if total:
            self.tokens_used += int(total)

    # -- conversations ---------------------------------------------------- #
    def create_chat(self):
        """Create a fresh conversation server-side and return its chat_id."""
        r = self._request("POST", "/v2/chats/new", json={
            "chatId": "",
            "models": [self.model],
            "project_id": "",
            "timestamp": int(time.time() * 1000),
            "chat_type": "t2t",
            "chat_mode": "normal",
        })
        data = r.json().get("data") or {}
        cid = data.get("id") or data.get("chat_id") or ""
        if not cid:
            raise QwenError("Could not create a new chat.")
        self._chat_id = cid
        self._parent_id = None
        self._parent_chat_id = None
        return cid

    def new_chat(self, title=""):
        # Legacy v1 endpoint is retired; v2 create is used instead.
        cid = self.create_chat()
        if title:
            try:
                self.rename_chat(cid, title)
            except QwenError:
                pass
        return {"id": cid}

    def list_chats(self, page=1):
        r = self._request("GET", "/v2/chats", base=API)
        data = r.json().get("data", []) or []
        chats = []
        for item in data:
            if isinstance(item, str):
                chats.append({"id": item})
            elif isinstance(item, dict):
                chats.append(item)
        return chats

    def get_chat(self, chat_id):
        r = self._request("GET", f"/v2/chats/{chat_id}", base=API)
        return r.json().get("data", {})

    def rename_chat(self, chat_id, title):
        r = self._request("POST", f"/v2/chats/{chat_id}", base=API,
                          json={"title": title})
        return r.json().get("success", False)

    def delete_chat(self, chat_id):
        r = self._request("DELETE", f"/v2/chats/{chat_id}", base=API)
        return r.json().get("success", False)

    def use_chat(self, chat_id):
        data = self.get_chat(chat_id)
        if not data or not data.get("id"):
            raise QwenError(f"Conversation {chat_id} not found.")
        self._chat_id = data.get("id")
        # Resume mid-conversation by continuing from the last response id.
        resp = data.get("currentResponseIds") or []
        self._parent_id = data.get("currentId") or (resp[0] if resp else None)
        return data

    # -- files ------------------------------------------------------------ #
    @staticmethod
    def _oss_sigv1_put(token: dict, file_path: str, body: bytes, content_type: str):
        """Upload bytes to Aliyun OSS using the STS token from
        /files/getstsToken, signing the PUT with OSS signature v1.

        Returns (status_code, error_text). The object then becomes readable
        at the pre-signed CDN url returned by getstsToken (`file_url`).
        """
        bucket = token["bucketname"]
        date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        headers = {
            "date": date,
            "x-oss-security-token": token["security_token"],
        }
        canon = []
        for k, v in sorted(headers.items()):
            lk = k.lower()
            if lk.startswith("x-oss-"):
                canon.append(f"{lk}:{v}")
        headers_string = "\n".join(canon) + "\n" if canon else ""
        resource = f"/{bucket}/{file_path}"
        string_to_sign = (f"PUT\n\n{content_type}\n{date}\n"
                          f"{headers_string}{resource}")
        sig = base64.b64encode(
            hmac.new(token["access_key_secret"].encode(),
                     string_to_sign.encode(), hashlib.sha1).digest()
        ).decode()
        headers["Authorization"] = f"OSS {token['access_key_id']}:{sig}"
        headers["Content-Type"] = content_type
        url = f"https://{bucket}.{token['region']}.aliyuncs.com/{file_path}"
        try:
            r = requests.put(url, data=body, headers=headers, timeout=60)
            return r.status_code, r.text[:300]
        except requests.RequestException as e:
            return 0, str(e)

    def upload_file(self, path: str):
        path = os.path.expanduser(path)
        if not os.path.isfile(path):
            raise QwenError(f"No such file: {path}")
        size = os.path.getsize(path)
        if size > 20 * 1024 * 1024:
            raise QwenError("File exceeds the 20 MB upload limit.")
        filename = os.path.basename(path)
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        ftype = (filename.rsplit(".", 1)[-1].lower()
                 if "." in filename else "file")
        r = self._request("POST", "/v2/files/getstsToken", base=API, json={
            "filename": filename,
            "filesize": str(size),
            "filetype": ftype,
        })
        token = (r.json().get("data") or {}) if r.content else {}
        if not token.get("file_id"):
            raise QwenError(token.get("message") or
                            (r.json().get("data") or {}).get("details")
                            or "Failed to get upload token")
        with open(path, "rb") as f:
            body = f.read()
        status, err = self._oss_sigv1_put(token, token["file_path"], body, ctype)
        if status != 200:
            raise QwenError(f"OSS upload failed ({status}): {err}")
        self.attachments.append({
            "file_id": token["file_id"],
            "url": token["file_url"],
            "name": filename,
            "size": size,
        })
        return {
            "id": token["file_id"],
            "url": token["file_url"],
            "filename": filename,
            "size": size,
        }

    # -- models & quota --------------------------------------------------- #
    def list_models(self):
        r = self._request("GET", "/models")
        data = r.json().get("data", [])
        return [m.get("id") for m in data if m.get("is_active", True)]

    def account_quota(self):
        # retries=1 so a flaky server 500 fails fast (~1s) instead of a
        # ~10s multi-retry stall in /status.
        r = self._request("POST", "/users/user/entitlement_quota",
                          json={"features": []}, retries=1)
        return r.json().get("data", {})

    def logout(self):
        info = self.whoami()
        uid = (info.get("user") or {}).get("id")
        if uid:
            try:
                self._request("POST", f"/users/logout/{uid}", retries=1)
            except QwenError:
                pass
        clear_token()
        self.token = None


# --------------------------------------------------------------------------- #
# CLI actions
# --------------------------------------------------------------------------- #
def login_with_browser(timeout: float = 300.0):
    """Open a real browser at chat.qwen.ai, wait for the user to log in and send
    one test message, capture the JWT + full cookie jar, and record the exact
    /chat/completions request the web app uses. The chat client then replays it."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        raise QwenError("Playwright is not installed (pip install playwright).")
    import shutil

    def _find_chromium():
        """Return a usable Chromium binary: a system one on PATH, else Playwright's
        bundled copy. Empty string means none found."""
        for name in ("chromium", "chromium-browser",
                     "google-chrome", "google-chrome-stable",
                     "google-chrome-unstable", "chrome"):
            exe = shutil.which(name)
            if exe:
                return exe
        return ""

    print("Opening browser…")
    exe = _find_chromium()
    token = ""
    captured = []

    def _record(resp):
        try:
            req = resp.request
            url = resp.url
            if "completions" not in url:
                return
            if req.method not in ("POST", "PUT"):
                return
            body = None
            try:
                body = req.post_data
            except Exception:
                body = None
            if not body:
                return
            ct = (resp.headers or {}).get("content-type", "")
            try:
                parsed = json.loads(body) if isinstance(body, str) else body
            except Exception:
                return
            sample = ""
            if "event-stream" in ct:
                try:
                    sample = resp.text()
                except Exception:
                    sample = ""
            if isinstance(sample, str) and len(sample) > 6000:
                sample = sample[:4000] + "\n...TRUNC...\n" + sample[-2000:]
            captured.append({
                "url": url,
                "method": req.method,
                "headers": {k: v for k, v in (req.headers or {}).items()},
                "body": parsed,
                "stream": "event-stream" in ct,
                "response_sample": sample,
            })
        except Exception:
            pass

    with sync_playwright() as p:
        kwargs = dict(headless=False, ignore_https_errors=True,
                      args=["--no-sandbox"])
        if exe:
            kwargs["executable_path"] = exe
        try:
            ctx = p.chromium.launch_persistent_context(
                str(CONFIG_DIR / "profile"), **kwargs)
        except Exception:
            # No system browser or it failed to launch — fall back to
            # Playwright's bundled Chromium (if installed), else guide install.
            if exe:
                kwargs.pop("executable_path", None)
                try:
                    ctx = p.chromium.launch_persistent_context(
                        str(CONFIG_DIR / "profile"), **kwargs)
                except Exception:
                    raise QwenError(
                        "Could not launch a Chromium browser.\n"
                        "Install one with either:\n"
                        "  pip install playwright && playwright install chromium\n"
                        "or a system package:\n"
                        "  apt install chromium   (or google-chrome)")
            else:
                raise QwenError(
                    "Could not launch a Chromium browser.\n"
                    "Install one with either:\n"
                    "  pip install playwright && playwright install chromium\n"
                    "or a system package:\n"
                    "  apt install chromium   (or google-chrome)")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("response", _record)
        try:
            page.goto(BASE_URL, timeout=45000, wait_until="domcontentloaded")
        except Exception as e:
            ctx.close()
            raise QwenError(f"Could not open {BASE_URL}: {e}")
        print("Log in in the browser window and complete any slider captcha.")
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                token = page.evaluate("() => localStorage.getItem('token') || ''")
            except Exception:
                token = ""
            if token:
                break
            time.sleep(1)
        if not token:
            ctx.close()
            raise QwenError("Timed out waiting for login. No token found in localStorage.")
        print("Session captured. Now send ONE test message (e.g. \"hello\") in the")
        print("browser window, then press Enter here to finish and store the request.")
        try:
            input("Press Enter when done… ")
        except (EOFError, KeyboardInterrupt):
            pass
        time.sleep(3)
        cookies = [{
            "name": c.get("name", ""), "value": c.get("value", ""),
            "domain": c.get("domain"), "path": c.get("path", "/"),
        } for c in ctx.cookies()]
        ctx.close()
    if not cookies:
        raise QwenError("Browser login succeeded but captured no cookies.")

    spec = None
    for c in captured:
        if c.get("body"):
            spec = {"url": c["url"], "method": c["method"],
                    "headers": c["headers"], "body": c["body"],
                    "stream": c["stream"],
                    "response_sample": c.get("response_sample", "")}
            break
    save_session(token, cookies)
    set_token(token)
    if spec:
        save_capture(spec)
        okmsg(f"Captured session + live chat request ({len(cookies)} cookies).")
    else:
        warn("Session saved, but no chat request was captured — send a message and re-run.")
    return token


def cmd_login(args):
    if getattr(args, "browser", False):
        try:
            login_with_browser()
        except QwenError as e:
            emsg(str(e))
            sys.exit(1)
        return

    cookie = getattr(args, "cookie", "")
    token = args.token

    # Optional: load a previously-captured chat request spec from a file so
    # headless installs can replay the web app's exact payload without a display.
    cap_file = getattr(args, "capture_file", "")
    if cap_file:
        cap_path = os.path.expanduser(cap_file)
        if not os.path.isfile(cap_path):
            emsg(f"Capture file not found: {cap_file}")
            sys.exit(1)
        try:
            cap = json.loads(Path(cap_path).read_text())
        except (json.JSONDecodeError, OSError) as e:
            emsg(f"Could not read capture file: {e}")
            sys.exit(1)
        if not cap.get("body") or not cap.get("url"):
            emsg("Capture file must have `url`, `method` and `body`.")
            sys.exit(1)
        save_capture(cap)
        okmsg(f"Loaded chat capture from {cap_file}.")

    if cookie:
        cookies = parse_cookie_str(cookie)
        if not cookies:
            emsg("No valid cookies in the provided string.")
            sys.exit(1)
        if not token:
            token = token_from_cookies(cookies)
        save_session(token or "", cookies)
        if token:
            set_token(token)
        okmsg(f"Stored {len(cookies)} cookies from string" + (f", token {mask_token(token)}" if token else " (no token)"))
        if not token:
            warn("No token found — pass --token or include a `token=` cookie for chat.")
        return

    if not token and args.email and args.password:
        token = QwenClient().signin(args.email, args.password)
    elif not token and args.email:
        pwd = getpass(f"Password for {args.email}: ")
        token = QwenClient().signin(args.email, pwd)

    if token:
        set_token(token)
        okmsg(f"Stored token: {mask_token(token)}")
        if not has_cookies():
            warn("Token stored, but chat needs browser cookies (anti-bot).")
            warn("Run `qwen.py login --browser`, or pass --cookie '<header>' from DevTools.")
        return

    if not args.token and not args.email and not cookie and not cap_file:
        _login_wizard(QwenClient())
        return

    print("Provide one of:")
    print("  --browser                    open a browser to log in (recommended)")
    print("  --cookie '<cookie header>'    paste cookies from DevTools (headless)")
    print("  --token <JWT>                 token from localStorage on chat.qwen.ai")
    print("  --capture-file <file.json>    load a saved chat request spec")
    print("  --email E --password P       login with credentials")
    return


def cmd_token(args):
    tok = get_token()
    if tok:
        cprint(f"[cyan]Token:[/cyan] {mask_token(tok)}")
        exp = _jwt_exp(tok)
        if exp:
            cprint(f"[cyan]Expires:[/cyan] {exp:%Y-%m-%d %H:%M UTC} ({'OK' if exp > datetime.now(timezone.utc) else 'EXPIRED'})")
    else:
        emsg("No token stored. Run `qwen.py login`.")


def _jwt_exp(token):
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(_b64url(payload))
        exp = data.get("exp")
        if exp:
            return datetime.fromtimestamp(exp, timezone.utc)
    except Exception:
        return None


def _b64url(s):
    import base64
    return base64.urlsafe_b64decode(s.encode()).decode()


def cmd_status(args, client=None):
    c = client or QwenClient()
    if not c.token:
        emsg("Not logged in. Run `qwen.py login` first.")
        return
    try:
        who = c.whoami()
    except QwenError as e:
        emsg(str(e))
        return
    panel(
        "Account",
        f"User   : {who.get('name') or who.get('id') or 'unknown'}\n"
        f"Email  : {who.get('email', 'n/a')}\n"
        f"Tier   : {who.get('tier', 'n/a')}\n"
        f"Model  : {c.model}\n"
        f"Reason : {getattr(c, 'reasoning', 'auto')} (auto/thinking/fast)\n"
        f"Token  : {mask_token(c.token)}\n"
        f"Cookies: {'captured' if has_cookies() else 'none'} (needed for chat)\n"
        f"Chat   : {c._chat_id or 'new (not yet saved)'}",
    )
    try:
        quota = c.account_quota()
    except QwenError as e:
        dim(f"Quota unavailable ({e}).")
        return
    if _quota_exhausted(quota):
        warn("Chat quota reached or exceeded — you may not be able to start new "
             "conversations. Check your plan or top up.")
    _print_quota(quota)


def _quota_exhausted(quota):
    """Best-effort detection that the user has run out of chat quota."""
    if not isinstance(quota, dict):
        return False
    qp = quota.get("quota_plan") or quota.get("quota") or quota
    if not isinstance(qp, dict):
        return False
    remaining = None
    for key in ("remaining", "remaining_tokens", "remained_quota"):
        val = qp.get(key)
        if val is not None:
            remaining = val
            break
    if remaining is not None:
        return int(remaining) <= 0
    total = None
    for key in ("total_quota", "totalTokens", "total_tokens", "quota_volume"):
        val = qp.get(key)
        if val is not None:
            total = val
            break
    used = None
    for key in ("used_quota", "usedTokens", "used_tokens", "used"):
        val = qp.get(key)
        if val is not None:
            used = val
            break
    if total is not None and used is not None:
        return int(used) >= int(total)
    # Last resort (some plans expose an absolute remaining number).
    for key in ("left", "left_quota", "available", "free_quota"):
        val = qp.get(key)
        if val is not None:
            return int(val) <= 0
    return False


def _print_quota(quota):
    table = Table(title="Tokens / Quota", box=box.SIMPLE_HEAD) if _RICH else None
    if table:
        table.add_column("Item")
        table.add_column("Value")
        rows = []
    else:
        rows = []
    qp = quota.get("quota_plan") or quota.get("quota") or quota
    if isinstance(qp, dict):
        for k, v in qp.items():
            rows.append((k, str(v)))
    elif isinstance(qp, list):
        for item in qp:
            if isinstance(item, dict):
                for k, v in item.items():
                    rows.append((f"{k}", str(v)))
    if not rows:
        rows.append(("raw", json.dumps(quota)[:2000]))
    if table:
        for k, v in rows:
            table.add_row(k, v)
        _console.print(table)
    else:
        for k, v in rows:
            print(f"{k:20} {v}")


def cmd_models(args):
    c = QwenClient()
    models = c.list_models()
    if not models:
        warn("No models returned (or not logged in).")
        return
    for m in models:
        cprint(f"[bold]{m}[/bold]" if m == c.model else m)
    dim(f"\nDefault: {c.model}  (switch with /model or --model)")


HISTORY_LIMIT = 12


def _history_sorted(chats):
    """Filter to dict chats with an id, newest-first by update/create time."""
    chats = [ch for ch in chats if isinstance(ch, dict) and ch.get("id")]
    chats.sort(key=lambda ch: ch.get("updated_at") or ch.get("created_at") or 0,
               reverse=True)
    return chats


def _history_note(n, limited):
    """Dim hint shown when the recent-conversation view is truncated."""
    if limited:
        dim(f"showing last {HISTORY_LIMIT} of {n} "
            f"— use '/history full' to list all")


def cmd_history(args):
    c = QwenClient()
    try:
        chats = c.list_chats()
    except QwenError as e:
        emsg(str(e))
        return
    chats = _history_sorted(chats)
    if not chats:
        dim("No saved conversations.")
        return
    full = bool(getattr(args, "full", False))
    limited = not full and len(chats) > HISTORY_LIMIT
    total = len(chats)
    if limited:
        chats = chats[:HISTORY_LIMIT]
    table = Table(title="Conversations", box=box.SIMPLE_HEAD) if _RICH else None
    rows = []
    for ch in chats:
        rows.append((
            ch.get("id", "?"),
            (ch.get("title") or "(untitled)")[:60],
            datetime.fromtimestamp(int(ch.get("created_at", 0)), timezone.utc).strftime("%Y-%m-%d %H:%M") if ch.get("created_at") else "?",
        ))
    if table:
        for cid, title, ts in rows:
            table.add_row(cid, title, ts)
        _console.print(table)
    else:
        for cid, title, ts in rows:
            print(f"{cid}  {title:60} {ts}")
    _history_note(total, limited)
    dim("\nResume with: qwen.py use <id>   or in REPL: /use <id>")


def _msg_answer(m):
    for e in (m.get("content_list") or []):
        if e.get("phase") == "answer" and e.get("content"):
            return e["content"]
    return m.get("content") or ""


def _grep_qwen_text(m):
    """Extract grep-able text from a Qwen message."""
    if m.get("role") == "assistant":
        return _msg_answer(m)
    return m.get("content") or ""


def _grep_ds_text(m):
    """Extract grep-able text from a DeepSeek message."""
    return m.get("content") or ""


def _grep_parse(tokens):
    """Parse `/grep <pattern> [targets...]` / `grep` tokens into a spec.

    The first token is the regex pattern. The rest recognise explicit chat ids
    (space- or comma-separated), `-n N`/`--last N` (N most recent), `-a`/`--all`,
    and `-i`/`--ignore-case`. Returns {'pattern', 'ids', 'last': int|None,
    'all': bool, 'incase': bool}."""
    ids = []
    last = None
    all_ = False
    incase = False
    pattern = None
    toks = list(tokens)
    if toks:
        pattern, toks = toks[0], toks[1:]
    i = 0
    while i < len(toks):
        t = toks[i]
        if t in ("-a", "--all"):
            all_ = True
        elif t in ("-i", "--ignore-case"):
            incase = True
        elif t in ("-n", "--last"):
            i += 1
            if i < len(toks) and toks[i].isdigit():
                last = int(toks[i])
        else:
            ids.extend(x for x in t.replace(",", " ").split() if x)
        i += 1
    return {"pattern": pattern, "ids": ids, "last": last,
            "all": all_, "incase": incase}


def _grep_scope(get_list, spec):
    """Resolve a grep spec to concrete chat ids (newest first).

    Explicit ids pass through; `last=N` takes the first N of the app's
    newest-first list; otherwise (no targets) everything is searched."""
    ids = list(spec.get("ids") or [])
    last = spec.get("last")
    if last and last > 0:
        try:
            chat_list = _history_sorted(get_list() or [])
        except Exception as e:
            emsg(f"Failed to list conversations: {e}")
            chat_list = []
        ids.extend(ch.get("id") for ch in chat_list[:last]
                   if isinstance(ch, dict) and ch.get("id"))
    elif not ids and not last:
        try:
            chat_list = _history_sorted(get_list() or [])
        except Exception as e:
            emsg(f"Failed to list conversations: {e}")
            chat_list = []
        ids.extend(ch.get("id") for ch in chat_list
                   if isinstance(ch, dict) and ch.get("id"))
    return ids


def _grep_compile(pattern, incase):
    """Compile the user regex, or None when the pattern is empty/invalid."""
    if not pattern:
        return None
    try:
        return re.compile(pattern, re.IGNORECASE if incase else 0)
    except re.error as e:
        emsg(f"Bad pattern: {e}")
        return None


def _grep_matches(text, rx):
    """Line-level matches: non-empty lines containing the pattern."""
    return [(i, ln) for i, ln in enumerate(text.splitlines(), 1)
            if ln.strip() and rx.search(ln)]


def _grep_highlight(line, rx):
    """Render a matching line, reversing matched spans when rich is available."""
    if not _RICH:
        return line
    txt = Text(line)
    for m in rx.finditer(line):
        txt.stylize("bold reverse", m.start(), m.end())
    return txt


def _grep_emit(role_label, matches, rx):
    """Print one message's matches; returns how many matched."""
    count = 0
    for lineno, line in matches:
        if _RICH:
            _console.print(f"[dim]{lineno:>4} [/dim][cyan]{role_label}:[/cyan]",
                           _grep_highlight(line, rx))
        else:
            print(f"{lineno:>4} {role_label}: {line}")
        count += 1
    return count


def _grep_conversation(cid, title, msgs, extract, rx):
    """Grep one conversation's messages; returns total hit count."""
    if not rx:
        return 0
    hits = 0
    for m in msgs:
        role = m.get("role")
        if role == "user":
            label = "You"
        elif role == "assistant":
            label = "Assistant"
        else:
            continue
        hits += _grep_emit(label, _grep_matches(extract(m), rx), rx)
    if hits:
        cprint(f"\n[bold]{title or '(untitled)'}[/bold]  ({cid})")
    return hits


def _grep_run(get_list, get_chat, extract, spec):
    """Run a grep across the resolved conversation scope.

    `get_list` yields conversation summaries (dicts with id/title), `get_chat`
    the transcript (`data["chat"]["messages"]` for Qwen, or a dict with
    `messages` for DeepSeek). Chats that can't be read are skipped with a dim
    note. Prints a `hits in matches of total` summary."""
    if spec.get("pattern") is None:
        emsg("usage: /grep <pattern> [chat_id ...] [-n N] [-a] [-i]")
        return
    rx = _grep_compile(spec["pattern"], spec.get("incase", False))
    if not rx:
        return
    ids = _grep_scope(get_list, spec)
    if not ids:
        dim("No conversations to search.")
        return
    total = len(ids)
    matched_chats = hits = 0
    for cid in ids:
        try:
            data = get_chat(cid)
        except Exception as e:
            dim(f"{cid}: {e}")
            continue
        if not data or not data.get("id"):
            dim(f"{cid}: no cached transcript")
            continue
        msgs = data.get("chat", {}).get("messages", data.get("messages") or [])
        n = _grep_conversation(cid, data.get("title") or "", msgs, extract, rx)
        if n:
            hits += n
            matched_chats += 1
    okmsg(f"{hits} match(es) in {matched_chats} of {total} conversation(s).")


def cmd_grep(args):
    c = QwenClient()
    spec = _grep_parse([args.pattern] + list(args.chat_id or []))
    if getattr(args, "last", None) is not None:
        spec["last"] = args.last
    spec["all"] = spec["all"] or bool(getattr(args, "all", False))
    spec["incase"] = spec["incase"] or bool(getattr(args, "ignore_case", False))
    _grep_run(c.list_chats, c.get_chat, _grep_qwen_text, spec)


def _print_conversation(data, full):
    cprint(f"[bold]{data.get('title') or '(untitled)'}[/bold]  ({data.get('id')})")
    if data.get("created_at") and data.get("updated_at"):
        dim(f"created {datetime.fromtimestamp(int(data['created_at']), timezone.utc):%Y-%m-%d %H:%M} "
            f"· updated {datetime.fromtimestamp(int(data['updated_at']), timezone.utc):%Y-%m-%d %H:%M}")
    limit = None if full else 3
    msgs = data.get("chat", {}).get("messages", [])
    for m in msgs:
        role = m.get("role")
        if role == "user":
            cprint(f"\n[cyan]You:[/cyan]")
            _print_msg(m.get("content") or "", limit)
        elif role == "assistant":
            cprint("\n[green]Qwen:[/green]")
            _print_msg(_msg_answer(m), limit)


def _print_msg(text, limit):
    if limit is None:
        markdown(text)
        return
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return
    for ln in lines[:limit]:
        _console.print(ln, highlight=False) if _RICH else print(ln)
    if len(lines) > limit:
        dim(f"    ... {len(lines) - limit} line(s) hidden (use: /print full)")
        return


def _offer_chat_code_saves(chat_id, data):
    """Offer to save every code block in a Qwen conversation (used by /view
    and /print full). Shares the same prompt style as the DS offer."""
    msgs = data.get("chat", {}).get("messages", [])
    blocks = []
    for m in msgs:
        if m.get("role") == "assistant":
            blocks.extend(_extract_code_blocks(_msg_answer(m)))
    if not blocks:
        return
    sess_dir = os.path.join(os.getcwd(), chat_id)
    os.makedirs(sess_dir, exist_ok=True)
    cprint(f"\n[bold yellow]>>> {len(blocks)} code block(s) in this session"
           f" — saving to {sess_dir}[/bold yellow]")
    for i, b in enumerate(blocks, 1):
        default = b["filename"] or f"block_{i}.{_lang_ext(b['lang'])}"
        _preview_block(i, b, default)
        try:
            inp = input(f"  save block {i} as [{default}]? "
                        f"(Enter=save, 'n'=skip, '/'=skip, or path): ")
        except EOFError:
            break
        except KeyboardInterrupt:
            print()
            dim("skipped the rest")
            break
        s = inp.strip()
        if s.lower() in ("n", "no"):
            continue
        if not s:
            path = os.path.join(sess_dir, default)
        elif os.path.isabs(s):
            path = s
        elif s.startswith("/"):
            path = s
        else:
            path = os.path.join(sess_dir, s)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(b["content"])
            okmsg(f"  saved -> {os.path.abspath(path)}")
        except OSError as ex:
            emsg(f"  could not write {path}: {ex}")


def cmd_view(args):
    c = QwenClient()
    try:
        data = c.get_chat(args.chat_id)
    except QwenError as e:
        emsg(str(e))
        return
    if not data or not data.get("id"):
        emsg(f"Conversation {args.chat_id} not found.")
        return
    _print_conversation(data, getattr(args, "full", False))
    _offer_chat_code_saves(args.chat_id, data)
    dim("\nResume from REPL with /use, or `qwen.py use <id>`")


def cmd_print(args):
    c = QwenClient()
    try:
        data = c.get_chat(args.chat_id)
    except QwenError as e:
        emsg(str(e))
        return
    if not data or not data.get("id"):
        emsg(f"Conversation {args.chat_id} not found.")
        return
    _print_conversation(data, args.full)


def cmd_new(args):
    c = QwenClient()
    c.new_chat()
    okmsg(f"Started new conversation: {c._chat_id}")


def cmd_use(args):
    c = QwenClient()
    try:
        data = c.use_chat(args.chat_id)
    except QwenError as e:
        emsg(str(e))
        return
    title = data.get("title") or "(untitled)"
    okmsg(f"Resumed conversation {args.chat_id} — {title}")
    repl(c, init_title=data.get("title") or "")


def _latest_chat_id():
    """Return the most recently updated conversation id, or None."""
    c = QwenClient()
    try:
        chats = c.list_chats()
    except QwenError as e:
        emsg(str(e))
        return None
    chats = [ch for ch in chats if isinstance(ch, dict) and ch.get("id")]
    if not chats:
        return None
    chats.sort(key=lambda ch: ch.get("updated_at") or ch.get("created_at") or 0,
               reverse=True)
    return chats[0]["id"]


def _parse_del_spec(tokens):
    """Split a delete-arguments token list (from `ds del`, `del`, or `/del`)
    into a spec dict.

    Accepts `-f`/`--force` (skip confirmation), `-n N`/`--last N` (delete the
    N most recent conversations), and any number of explicit chat ids
    (space- or comma-separated). Returns {'ids': [...], 'last': int|None,
    'force': bool}."""
    ids = []
    last = None
    force = False
    toks = list(tokens)
    i = 0
    while i < len(toks):
        t = toks[i]
        if t in ("-f", "--force"):
            force = True
        elif t in ("-n", "--last"):
            i += 1
            if i < len(toks) and toks[i].isdigit():
                last = int(toks[i])
        else:
            ids.extend(x for x in t.replace(",", " ").split() if x)
        i += 1
    return {"ids": ids, "last": last, "force": force}


def _del_targets(get_list_fn, spec):
    """Resolve a delete spec to concrete chat ids using the app's list source.

    Explicit ids pass through unchanged; `last=N` takes the first N entries of
    the app's conversation list (newest first for DeepSeek). Returns
    (ids, force)."""
    ids = list(spec.get("ids") or [])
    last = spec.get("last")
    if last and last > 0:
        try:
            chat_list = get_list_fn() or []
        except Exception as e:
            emsg(f"Failed to list conversations: {e}")
            chat_list = []
        for ch in chat_list[:last]:
            cid = ch.get("id") if isinstance(ch, dict) else ch
            if cid:
                ids.append(cid)
    return ids, bool(spec.get("force"))


def _bulk_delete(ids, delete_fn, active_id=None, force=False):
    """Delete several conversations, reporting a summary.

    Asks for confirmation when deleting more than one conversation unless
    `force`. Returns (deleted, missing, active_gone) where active_gone is
    True when `active_id` (e.g. the thread the REPL is on) was among them."""
    if not ids:
        emsg("Nothing to delete.")
        return 0, 0, False
    if len(ids) > 1 and not force:
        shown = ", ".join(str(i) for i in ids[:5])
        if len(ids) > 5:
            shown += f", … (+{len(ids) - 5} more)"
        if not ask_yes_no(f"Delete {len(ids)} conversation(s) ({shown})?", False):
            dim("Cancelled.")
            return 0, 0, False
    deleted = missing = 0
    active_gone = False
    for cid in ids:
        try:
            ok = bool(delete_fn(cid))
        except Exception as e:
            emsg(f"{cid}: {e}")
            continue
        if ok:
            deleted += 1
            if active_id and str(cid) == str(active_id):
                active_gone = True
        else:
            missing += 1
            dim(f"{cid}: not found")
    if deleted:
        okmsg(f"Deleted {deleted}/{len(ids)} conversation(s).")
    if missing:
        emsg(f"{missing} conversation(s) not found.")
    return deleted, missing, active_gone


def cmd_delete(args):
    c = QwenClient()
    spec = _parse_del_spec(args.chat_id)
    if getattr(args, "last", None) is not None:
        spec["last"] = args.last
    spec["force"] = spec["force"] or getattr(args, "force", False)
    ids, force = _del_targets(c.list_chats, spec)
    if not ids:
        emsg("usage: qwen.py del <chat_id>... [-n N] [-f]")
        return
    _bulk_delete(ids, c.delete_chat, force=force)


def cmd_ask(args):
    c = QwenClient()
    if args.model:
        c.model = args.model
    if getattr(args, "reasoning", None):
        c.reasoning = args.reasoning
    if not c.token:
        emsg("Not logged in. Run `qwen.py login` first.")
        return
    text = args.message
    if not text and not sys.stdin.isatty():
        text = sys.stdin.read().strip()
    if not text:
        emsg("Nothing to ask. Use: qwen.py ask \"your question\"")
        return
    for f in args.upload or []:
        try:
            info = c.upload_file(f)
            okmsg(f"Uploaded {info.get('id', '?')}")
        except QwenError as e:
            emsg(str(e))
            return
    if not getattr(args, "no_stream", False):
        full, usage, chat_id = c.stream_chat(text, on_delta=_stream_write,
                                             on_reason=_make_reason_writer())
        print()
    else:
        full, usage, chat_id = c.nonstream_chat(text)
        print(full)
    _usage_line(usage, chat_id)


def _usage_line(usage, chat_id):
    if usage:
        u = f"{usage.get('total_tokens', '?')} tokens"
        dim(f"({u} | chat {chat_id or 'new'})")
    else:
        dim(f"(chat {chat_id or 'new'})")


def cmd_sandbox(args):
    if sandbox is None:
        emsg("sandbox.py not found next to qwen.py.")
        return
    if args.list:
        p = sandbox.load_policy("policy.toml")
        for line in p.describe():
            print(f"  {line}")
        return
    report = sandbox.check("policy.toml")
    cprint(f"backend:      {report['backend']}")
    cprint(f"bwrap:        {'yes (' + report['bwrap_path'] + ')' if report['bwrap_path'] else 'no'}")
    cprint(f"docker:       {'yes' if report['docker'] else 'no'}")
    cprint(f"network:      {report['network_default']} (default)")
    probe = report.get("probe")
    if probe:
        cprint(f"bwrap probe:  {probe}"
               + (f" — {report.get('probe_detail')}" if report.get("probe_detail") else ""))
    pol = report.get("policy")
    cprint(f"policy:       {pol}" if pol else "policy:      not checked")
    if report["backend"] == "restricted":
        warn("restricted backend: no namespace isolation. Install bubblewrap:")
        dim(sandbox.install_hint())


def cmd_run(args):
    if sandbox is None:
        emsg("sandbox.py not importable next to qwen.py.")
        return
    if not args.run_args:
        emsg("usage: qwen.py run <command...> [--net] [--timeout N]")
        return
    text = " ".join(args.run_args)
    try:
        argv = sandbox.parse(text)
    except ValueError as e:
        emsg(f"parse error: {e}")
        return
    try:
        res = sandbox.run(
            argv,
            workspace=args.workspace, network=args.net,
            timeout_s=args.timeout, max_out=args.max_out,
            backend=args.sandbox,
            approve=None,
        )
    except sandbox.SandboxError as e:
        emsg(str(e))
        return
    except PermissionError as e:
        emsg(f"not auto-approved (headless run only executes oracle commands): "
             f"{e}")
        return
    _show_result(res)


def _agent_progress(step, verdict, argv, feedback):
    print()
    warn(f"[step {step}] {verdict}: {sandbox.cmdline(argv)}")
    print(feedback.rstrip()[:1000])
    if len(feedback) > 1000:
        dim(f"… (truncated preview; full output sent to model)")


def cmd_agent(args):
    """Autonomous sandboxed agent loop: qwen.py agent <task...>"""
    if agent_mod is None:
        emsg("agent.py not found next to qwen.py.")
        return
    if not args.task:
        emsg("usage: qwen.py agent <task...> [--tier oracle|mutator|interpreter]")
        return
    task = " ".join(args.task)
    client = QwenClient()
    if not client.token:
        emsg("Not logged in. Run `qwen.py login` first.")
        return
    try:
        client.new_chat()
        okmsg(f"Agent session: chat {client._chat_id}")
    except QwenError as e:
        emsg(f"could not start chat: {e}")
        return
    try:
        res = agent_mod.agent_loop(
            client,
            task,
            tier=args.tier,
            workspace=args.workspace or os.getcwd(),
            workspace_ro=args.workspace_ro,
            max_steps=args.steps,
            timeout_s=args.timeout,
            max_out=args.max_out,
            backend=args.sandbox,
            interactive=True,
            allow_interpreters=args.allow_interpreters,
            on_result=_agent_progress,
            log_path=args.log,
        )
    except agent_mod.AgentError as e:
        emsg(str(e))
        return
    print()
    if res["status"] == "done":
        okmsg(f"Done in {res['steps']} steps ({res['duration']}s)")
        if res["summary"]:
            dim(f"summary: {res['summary']}")
    else:
        warn(f"Reached the step cap ({res['steps']} steps) without ```done```.")
    if res.get("usage"):
        dim("tokens: " + str(res["usage"].get("total_tokens", "?")))
    if args.log:
        okmsg(f"log: {args.log}")


def cmd_ds(args):
    """Talk to DeepSeek through the local Deepseek-API proxy (`python app.py`
    inside the Deepseek-API/ repo, which speaks OpenAI at :8000/v1)."""
    if deepseek_client is None:
        emsg("deepseek_client module not found next to qwen.py.")
        return
    base = args.base_url or None
    model = deepseek_client.normalize_model(args.model or deepseek_client.DEFAULT_MODEL)
    if base:
        import os
        os.environ["DEEPSEEK_BASE_URL"] = base
    c = deepseek_client.DeepSeekSession(model=model)
    # Seed the session toggles from explicit CLI flags only (`--thinking` /
    # `--search`); a resumed conversation (`-c`, use) then restores its own
    # stored state, and an absent flag leaves the thread state untouched,
    # matching the web UI's per-conversation buttons.
    if getattr(args, "thinking", None) is not None:
        c.thinking = args.thinking
    if getattr(args, "search", None) is not None:
        c.search = args.search

    # Attach any --upload files before a conversation starts (ask/chat/use).
    if getattr(args, "upload", None) and args.sub in ("ask", "chat", "use"):
        for path in args.upload:
            try:
                info = c.upload_file(path)
                okmsg(f"Attached {path} → {info.get('id', '?')}")
            except deepseek_client.DeepSeekError as e:
                emsg(str(e))

    if args.sub == "models":
        try:
            for m in c.list_models():
                cprint(m)
        except deepseek_client.DeepSeekError as e:
            emsg(str(e))
        finally:
            c.close()
        return

    # `-c` continues the most recent saved conversation into the REPL (works
    # from either position: `qwen.py ds -c` or `qwen.py -c ds`).
    if getattr(args, "continue_ds", False) or getattr(args, "continue_", False):
        if args.sub in ("ask", "chat"):
            latest = next((ch["id"] for ch in c.store.list() if ch.get("id")), None)
            if latest:
                try:
                    data = c.use_chat(latest)
                    okmsg(f"Resumed last conversation {latest} — "
                          f"{data.get('title') or '(untitled)'}")
                    _warn_ds_pending(data)
                    ds_repl(c, args, init_title=data.get("title") or "")
                except deepseek_client.DeepSeekError as e:
                    emsg(str(e))
                c.close()
                return
            warn("No saved DeepSeek conversations.")
        else:
            dim("-c ignored for sub '{}' (only ask/chat).".format(args.sub))

    if args.sub == "chat":
        ds_repl(c, args)
        c.close()
        return

    if args.sub == "history":
        chats = c.list_chats()
        if not chats:
            dim("No saved conversations.")
            c.close()
            return
        rest = getattr(args, "rest", None) or []
        full = "-f" in rest or "--full" in rest or "full" in rest
        limited = not full and len(chats) > HISTORY_LIMIT
        total = len(chats)
        if limited:
            chats = chats[:HISTORY_LIMIT]
        if not c.online_ok:
            dim("(local only — online unreachable)")
        table = Table(title="DeepSeek conversations", box=box.SIMPLE_HEAD) if _RICH else None
        rows = []
        for ch in chats:
            rows.append((
                ch.get("id", "?"),
                (ch.get("title") or "(untitled)")[:60],
                datetime.fromtimestamp(int(ch.get("updated_at", 0)), timezone.utc).strftime("%Y-%m-%d %H:%M") if ch.get("updated_at") else "?",
                ch.get("model", ""),
            ))
        if table:
            for cid_, title, ts, model in rows:
                table.add_row(cid_, title, ts, model)
            _console.print(table)
        else:
            for cid_, title, ts, model in rows:
                print(f"{cid_}  {title:50} {ts}  {model}")
        _history_note(total, limited)
        c.close()
        return

    if args.sub == "sync":
        try:
            s = c.sync_chats()
            okmsg(f"pruned: {s['pruned']}  added: {s['added']}  updated: {s['updated']}")
        except deepseek_client.DeepSeekError as e:
            emsg(str(e))
        c.close()
        return

    if args.sub == "new":
        c.new_conversation()
        okmsg("New DeepSeek conversation (saved on first message).")
        c.close()
        return

    if args.sub == "use":
        if not args.rest or not args.rest[0]:
            emsg("usage: qwen.py ds use <chat_id>")
            c.close()
            return
        chat_id = args.rest[0]
        try:
            data = c.use_chat(chat_id)
            okmsg(f"Resumed: {data.get('title') or '(untitled)'}")
            _warn_ds_pending(data)
            ds_repl(c, args, init_title=data.get("title") or "")
        except deepseek_client.DeepSeekError as e:
            emsg(str(e))
        c.close()
        return

    if args.sub == "del":
        spec = _parse_del_spec(args.rest)
        if getattr(args, "last", None) is not None:
            spec["last"] = args.last
        spec["force"] = spec["force"] or getattr(args, "force", False)
        ids, force = _del_targets(c.list_chats, spec)
        if not ids:
            emsg("usage: qwen.py ds del <chat_id> [<chat_id> ...] [-n N] [-f]")
            c.close()
            return
        _bulk_delete(ids, c.delete_chat, force=force)
        c.close()
        return

    if args.sub == "grep":
        spec = _grep_parse(args.rest)
        if getattr(args, "last", None) is not None:
            spec["last"] = args.last
        spec["all"] = spec["all"] or bool(getattr(args, "all", False))
        spec["incase"] = spec["incase"] or bool(getattr(args, "ignore_case", False))
        if spec.get("pattern") is None:
            emsg("usage: qwen.py ds grep <pattern> [chat_id ...] [-n N] [-a] [-i]")
            c.close()
            return
        _grep_run(c.list_chats, c.get_chat, _grep_ds_text, spec)
        c.close()
        return

    if args.sub == "view":
        if not args.rest or not args.rest[0]:
            emsg("usage: qwen.py ds view <chat_id>")
            c.close()
            return
        cid = args.rest[0]
        chat = c.get_chat(cid)
        if not chat:
            _maybe_online_ds_chat(c, cid)
        else:
            _print_ds_chat(chat, True)
            _offer_ds_code_saves(c, cid)
        c.close()
        return

    if args.sub == "print":
        parts = list(args.rest or [])
        full = bool(parts) and parts[0].lower() in ("full", "true", "1", "y")
        if full:
            parts = parts[1:]
        if not parts:
            emsg("usage: qwen.py ds print [full] <chat_id>")
            c.close()
            return
        cid = parts[0]
        chat = c.get_chat(cid)
        if not chat:
            _maybe_online_ds_chat(c, cid)
        else:
            _print_ds_chat(chat, full)
            if full:
                _offer_ds_code_saves(c, cid)
        c.close()
        return

    # ask
    msg = " ".join(args.rest or []) if args.sub == "ask" else " ".join([args.sub or ""] + list(args.rest or []))
    if not msg:
        emsg('Nothing to ask. Use: qwen.py ds "your question"')
        c.close()
        return
    try:
        if args.no_stream:
            ftx, cid, usage = c.chat_once(msg, thinking=c.thinking,
                                          search=c.search)
            cprint(ftx)
        else:
            ftx, cid, usage = c.stream_chat(
                msg, thinking=c.thinking, search=c.search,
                on_delta=_stream_write)
            print()
        _show_links(ftx)
        _usage_line(usage, cid)
    except deepseek_client.DeepSeekError as e:
        emsg(str(e))
    finally:
        c.close()


# --------------------------------------------------------------------------- #
# Interactive REPL
# --------------------------------------------------------------------------- #
def _ds_repl_help():
    print("""
Commands:
  /help            this help
  /model <name>    switch model (deepseek-chat Instant / deepseek-expert Expert)
  /models          list available models
  /upload <path>   attach a file (repeatable)
  /files           list files attached to this session
  /clearfiles      drop all attached files
  /new             start a fresh conversation
  /multi           toggle multiline input (end with a blank line)
  /status          current model + conversation
  /think           toggle DeepThink for subsequent messages
  /search          toggle web search for subsequent messages
  /history         list saved conversations (synced from the online account)
  /grep <pattern> [ids...] [-n N | -a]  search conversations (default: all)
  /sync            refresh from online: prune deleted, add missing, fix titles
  /use <id>        resume a saved conversation
  /view <id>       print a conversation + offer to save code blocks
  /download        save the code blocks from the last reply (or /download <id>)
  /print [full]    print current or given conversation (short unless 'full')
  /rename <title>  rename current conversation
  /del <id>... [-n N] [-f] delete conversations (ids or the N most recent)
  /save <path>     export this chat to .md — /save <id> [path] exports a stored chat
  /status          current thread — model, conversation_id, turns
  /show :info      current thread incl. origin (forked from <id>?)
  /run <cmd> [--net] [--timeout N] run sandboxed and feed result to the model
  /exit, /quit     leave
  !<cmd>            run locally in your shell (no sandbox, no policy)
Anything else is sent to DeepSeek via the local proxy.
Links appearing in replies are listed automatically below the answer.
""")


def _prompt_input(prompt):
    """input() that renders rich markup so REPL prompts can be colored. Falls
    back to plain input() when rich isn't available (markup read literally)."""
    if _RICH:
        return _console.input(prompt)
    return input(prompt)


def _repl_prompt(model, conv_title="", thinking=None, search=None,
                 reasoning=None):
    """Colored REPL prompt. Model in bold cyan, conversation title in dim
    yellow when active, plus full-state markers for the toggles the REPL uses:
    [think:on|off], [search:on|off] (DeepSeek) and [reason:auto|thinking|fast]
    (Qwen). A toggle left as None (`thinking`/`search`) means "not applicable"
    and renders no marker. Falls back to plain text when rich isn't available."""
    flags = ""
    if thinking is not None:
        if thinking:
            flags += "[magenta][think:on][/magenta]"
        else:
            flags += "[dim][think:off][/dim]"
    if search is not None:
        if search:
            flags += "[cyan][search:on][/cyan]"
        else:
            flags += "[dim][search:off][/dim]"
    if reasoning is not None:
        flags += "[green][reason:{}][/green]".format(reasoning or "auto")
    if _RICH:
        title = f"[yellow]{conv_title}[/yellow]" if conv_title else ""
        sep = "[dim]|[/dim]" if title else ""
        return f"\n[bold cyan]{model}[/bold cyan]{sep}{title}{flags} [bold]>[/bold] "
    title = f"| {conv_title}" if conv_title else ""
    plain = f"{model}{title}"
    if thinking is not None:
        plain += f"(think:{'on' if thinking else 'off'})"
    if search is not None:
        plain += f"(search:{'on' if search else 'off'})"
    if reasoning is not None:
        plain += f"(reason:{reasoning or 'auto'})"
    return f"\n{plain}> "


def _input_multiline(first_prompt, cont_prompt="[dim]  ... [/dim]"):
    """Read a multiline message. The first prompt is shown for the first line,
    then a continuation prompt until a blank line (or Ctrl-D) ends it.
    Ctrl-C aborts and returns "". Returns the joined message."""
    lines: list[str] = []
    try:
        while True:
            line = _prompt_input(first_prompt if not lines else cont_prompt)
            if not line:
                break
            lines.append(line)
    except KeyboardInterrupt:
        print()
        return ""
    except EOFError:
        print()
    return "\n".join(lines)


def ds_repl(c, args, init_title=""):
    """DeepSeek REPL — same slash commands as the Qwen REPL, backed by the
    DeepSeek session's local conversation store."""
    init_readline()
    cprint(Panel.fit(f"DeepSeek proxy REPL — {c.model}", border_style="magenta"))
    dim("Type /help for commands, /exit to quit.")

    conv_title = init_title
    multiline = False
    last_reply = ""
    while True:
        prompt = _repl_prompt(c.model, conv_title, c.thinking, c.search)
        if multiline:
            user = _input_multiline(prompt).strip()
        else:
            try:
                user = _prompt_input(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
        if not user:
            continue

        if user.startswith("!"):
            _run_shell(user[1:].strip())
            continue

        if user.startswith("/"):
            cmd, _, arg = user[1:].partition(" ")
            arg = arg.strip()
            if cmd in ("exit", "quit"):
                break
            elif cmd == "multi":
                multiline = not multiline
                okmsg(f"Multiline input {'on' if multiline else 'off'} — "
                      f"{'end with a blank line.' if multiline else ''}")
            elif cmd == "help":
                _ds_repl_help()
            elif cmd == "model":
                if not arg:
                    warn(f"Current model: {c.model}")
                else:
                    resolved = deepseek_client.normalize_model(arg)
                    if resolved not in deepseek_client.KNOWN_MODELS:
                        emsg(f"Unknown model {arg!r}. Available: "
                             + ", ".join(deepseek_client.KNOWN_MODELS))
                    else:
                        c.model = resolved
                        okmsg(f"Switched to {c.model}")
            elif cmd == "models":
                try:
                    for m in c.list_models():
                        cprint(m)
                except deepseek_client.DeepSeekError as e:
                    emsg(str(e))
            elif cmd == "upload":
                if not arg:
                    emsg("usage: /upload <path>")
                    continue
                try:
                    info = c.upload_file(arg)
                    fname = info.get("file_name") or arg
                    note = f"  (uploaded as {fname})" if fname != arg else ""
                    okmsg(f"Attached {arg} → {info.get('id', '?')}{note}")
                    if c.conversation_id:
                        dim("This conversation has already started — sending the "
                            "next message will start a new forked thread seeded "
                            "with this file.")
                except deepseek_client.DeepSeekError as e:
                    emsg(str(e))
            elif cmd == "files":
                if not c.attachments:
                    dim("No files attached.")
                else:
                    for a in c.attachments:
                        print(f"  {a['id']}  {a['name']}  ({a['size']} B)")
            elif cmd == "clearfiles":
                c.attachments.clear()
                okmsg("Cleared attachments.")
            elif cmd == "think":
                # toggle DeepThink in-session; ask/chat default off.
                c.thinking = not c.thinking
                okmsg(f"DeepThink {'on' if c.thinking else 'off'}")
            elif cmd == "search":
                # toggle web search in-session; ask/chat default off.
                c.search = not c.search
                okmsg(f"WebSearch {'on' if c.search else 'off'}")
            elif cmd in ("new", "reset"):
                c.new_conversation()
                conv_title = ""
                okmsg("New conversation.")
            elif cmd == "status":
                dim(f"model: {c.model} | base: {c.base_url}" if _RICH
                    else f"model: {c.model}  base: {c.base_url}")
                dim(f"DeepThink: {'on' if c.thinking else 'off'}   "
                    f"WebSearch: {'on' if c.search else 'off'}")
                if c.conversation_id:
                    dim(f"conversation_id: {c.conversation_id}")
                    dim(f"turns in thread: {len(c.log) // 2}")
                else:
                    dim("no conversation yet — send a message")
            elif cmd in ("show",):
                # /show :info — current thread info incl. fork origin
                cid = _cid_key(c)
                if not cid:
                    emsg("no conversation yet — send a message first")
                    continue
                main = c.get_chat(cid) or {}
                print(f"current thread: {cid}")
                if main.get("title"):
                    print(f"  title:        {main['title']}")
                print(f"  model:        {c.model}")
                print(f"  turns:        {len(c.log) // 2}")
                print(f"  attachments:  {len(c.attachments)}")
                if c._forked_from:
                    old = _cid_key(c._forked_from)
                    print(f"  forked from:  {old}  (resume with /use {old})")
                else:
                    print("  forked from:  (this thread)")
            elif cmd == "history":
                chats = c.list_chats()
                if not chats:
                    dim("No saved conversations.")
                    continue
                full = arg.strip().lower() in ("full", "all")
                limited = not full and len(chats) > HISTORY_LIMIT
                total = len(chats)
                if limited:
                    chats = chats[:HISTORY_LIMIT]
                if not c.online_ok:
                    dim("(local only — online unreachable)")
                table = Table(title="DeepSeek conversations", box=box.SIMPLE_HEAD) if _RICH else None
                rows = []
                for ch in chats:
                    rows.append((
                        ch.get("id", "?"),
                        (ch.get("title") or "(untitled)")[:60],
                        datetime.fromtimestamp(int(ch.get("updated_at", 0)), timezone.utc).strftime("%Y-%m-%d %H:%M") if ch.get("updated_at") else "?",
                        ch.get("model", ""),
                    ))
                if table:
                    for cid_, title, ts, model in rows:
                        table.add_row(cid_, title, ts, model)
                    _console.print(table)
                else:
                    for cid_, title, ts, model in rows:
                        print(f"{cid_}  {title:50} {ts}  {model}")
                _history_note(total, limited)
            elif cmd == "sync":
                try:
                    s = c.sync_chats()
                    okmsg(f"pruned: {s['pruned']}  added: {s['added']}  updated: {s['updated']}")
                except deepseek_client.DeepSeekError as e:
                    emsg(str(e))
            elif cmd == "use":
                if not arg:
                    emsg("usage: /use <chat_id>")
                    continue
                try:
                    data = c.use_chat(arg)
                    conv_title = data.get("title") or ""
                    okmsg(f"Resumed: {data.get('title') or '(untitled)'}")
                    _print_ds_chat(data, False)
                except deepseek_client.DeepSeekError as e:
                    emsg(str(e))
            elif cmd == "print":
                parts = arg.split()
                if parts and parts[0].lower() in ("full", "true", "1", "y"):
                    full, rest = True, parts[1:]
                else:
                    full, rest = False, parts
                cid = rest[0] if rest else (_cid_key(c))
                if not cid:
                    emsg("No conversation yet. Send a message or use /print full <id>.")
                    continue
                chat = c.get_chat(cid)
                if not chat:
                    emsg(f"Conversation {cid} not found.")
                    continue
                _print_ds_chat(chat, full)
                if full:
                    _offer_ds_code_saves(c, cid)
            elif cmd == "view":
                cid = arg or _cid_key(c)
                if not cid:
                    emsg("usage: /view <chat_id>")
                    continue
                chat = c.get_chat(cid)
                if not chat:
                    emsg(f"Conversation {cid} not found.")
                    continue
                _print_ds_chat(chat, True)
                _offer_ds_code_saves(c, cid)
            elif cmd == "download":
                # /download          -> save code blocks from the last reply
                # /download <id>     -> save every code block in a chat
                if arg:
                    cid = arg
                    chat = c.get_chat(cid)
                    if not chat:
                        emsg(f"Conversation {cid} not found.")
                        continue
                    label = f"ds-{cid}"
                    blocks = _dl_chat_blocks(chat, lambda m: m.get("content") or "")
                    _offer_download_blocks(label, blocks)
                elif last_reply:
                    label = f"ds-{_cid_key(c)}" if _cid_key(c) else "ds-live"
                    _offer_download_blocks(label, _dl_blocks_text(last_reply))
                else:
                    emsg("No reply yet. Send a message or use /download <chat_id>.")
            elif cmd == "rename":
                if not arg:
                    emsg("usage: /rename <title>")
                elif not _cid_key(c):
                    emsg("No conversation to rename — send a message first.")
                else:
                    try:
                        if c.rename_chat(_cid_key(c), arg):
                            conv_title = arg
                            okmsg("Renamed.")
                        else:
                            emsg("No conversation to rename — send a message first.")
                    except deepseek_client.DeepSeekError as e:
                        emsg(str(e))
            elif cmd == "grep":
                spec = _grep_parse(arg.split())
                if spec.get("pattern") is None:
                    emsg("usage: /grep <pattern> [chat_id ...] [-n N] [-a] [-i]")
                    continue
                _grep_run(c.list_chats, c.get_chat, _grep_ds_text, spec)
            elif cmd == "del":
                spec = _parse_del_spec(arg.split())
                if not spec["ids"] and not spec["last"]:
                    emsg("usage: /del <chat_id> [<chat_id> ...] [-n N] [-f]")
                    continue
                ids, force = _del_targets(c.list_chats, spec)
                if not ids:
                    emsg("Nothing to delete.")
                    continue
                try:
                    _, _, active_gone = _bulk_delete(
                        ids, c.delete_chat, active_id=_cid_key(c), force=force)
                except deepseek_client.DeepSeekError as e:
                    emsg(str(e))
                    continue
                if active_gone:
                    conv_title = ""
            elif cmd == "save":
                # /save          -> export the current conversation to .md
                # /save <path>   -> same, explicit path
                # /save <id> [path] -> export a stored conversation to .md
                save_parts = arg.split()
                if save_parts and not save_parts[0].startswith(("/", ".")) and c.get_chat(save_parts[0]):
                    chat_id = save_parts[0]
                    path = save_parts[1] if len(save_parts) > 1 else f"{chat_id}.md"
                    chat = c.get_chat(chat_id)
                    title = chat.get("title") or chat_id
                    doc = _conversation_to_md(title, chat.get("messages") or [],
                                              lambda m: m.get("content") or "")
                    _save_md(path, doc)
                    okmsg(f"Saved conversation {chat_id} to {path}")
                else:
                    # No explicit chat id: prefer the live conversation (fetch
                    # the full stored chat we've resumed/created) over c.log,
                    # which stays empty after /use.
                    path = arg or f"deepseek-transcript-{time.strftime('%Y%m%d-%H%M%S')}.md"
                    cur = c.get_chat(c.conversation_id or "") if c.conversation_id else None
                    msgs = (cur or {}).get("messages") or []
                    if msgs:
                        title = (cur or {}).get("title") or c.conversation_id
                        doc = _conversation_to_md(title, msgs,
                                                  lambda m: m.get("content") or "")
                        _save_md(path, doc)
                        okmsg(f"Saved conversation {c.conversation_id} to {path}")
                    else:
                        _save_transcript([(m["role"], m["content"]) for m in c.log], path)
                        okmsg(f"Saved to {path}")
            elif cmd == "token":
                dim(f"Proxy: {c.base_url}")
            elif cmd == "run":
                if not arg:
                    emsg("usage: /run <cmd> [--net] [--timeout N]")
                    continue
                if sandbox is None:
                    emsg("sandbox.py not available — cannot /run")
                    continue
                network = False
                timeout_s = sandbox.DEFAULT_TIMEOUT
                tokens = arg.split()
                kept = []
                i = 0
                while i < len(tokens):
                    t = tokens[i]
                    if t == "--net":
                        network = True
                    elif t == "--timeout":
                        try:
                            timeout_s = int(tokens[i + 1])
                            i += 1
                        except (IndexError, ValueError):
                            emsg("--timeout needs a number")
                            timeout_s = sandbox.DEFAULT_TIMEOUT
                    else:
                        kept.append(t)
                    i += 1
                cmd_text = " ".join(kept).strip()
                if not cmd_text:
                    emsg("usage: /run <cmd> [--net] [--timeout N]")
                    continue
                status, feed = _run_cmd_feed(
                    cmd_text, workspace=os.getcwd(), network=network,
                    timeout_s=timeout_s)
                if status == "declined":
                    dim(f"declined: {cmd_text}")
                    continue
                if status != "ok":
                    emsg(feed)
                    continue
                user = (f"I ran the command: {cmd_text}\n"
                        f"(network: {'on' if network else 'off'})\n\n"
                        f"Sandboxed output:\n\n{feed}")
                cprint("[magenta]DeepSeek:[/magenta]")
                try:
                    if args.no_stream:
                        ftx, cid, usage = c.chat_once(
                            user, thinking=c.thinking, search=c.search)
                    else:
                        ftx, cid, usage = c.stream_chat(
                            user, thinking=c.thinking, search=c.search,
                            on_delta=_stream_write)
                        print()
                except deepseek_client.DeepSeekError as e:
                    emsg(str(e))
                    continue
                _show_links(ftx)
                _usage_line(usage, cid)
                _show_fork_notice(c)
            else:
                warn(f"Unknown command /{cmd}. Try /help.")
            continue

        cprint("[magenta]DeepSeek:[/magenta]")
        try:
            if args.no_stream:
                ftx, cid, usage = c.chat_once(user, thinking=c.thinking, search=c.search)
                markdown(ftx)
            else:
                ftx, cid, usage = c.stream_chat(
                    user, thinking=c.thinking, search=c.search,
                    on_delta=_stream_write)
                print()
        except deepseek_client.DeepSeekError as e:
            emsg(str(e))
            continue
        _show_links(ftx)
        last_reply = ftx
        _dl_hint(ftx)
        _show_fork_notice(c)
        if not c.forked and cid:
            dim(f"(conversation {_cid_key(c)})")
        if not conv_title:
            stored = c.get_chat(_cid_key(c)) or {}
            conv_title = stored.get("title") or ""


def _cid_key(c):
    """Stable chat id for the current DeepSeek thread (session uuid). Accepts
    the session object or a raw conversation_id string."""
    s = c.conversation_id if hasattr(c, "conversation_id") else c
    return (s or "").split(":", 1)[0]


def _show_fork_notice(c):
    """After a reply that forked the thread (file attached to a running
    conversation), print the new and old thread ids and clear the flags."""
    if not c.forked:
        return
    new_id = _cid_key(c)
    old_id = _cid_key(c._forked_from or "")
    dim("Started a new forked thread (file attached to a running "
        "conversation). The old thread is preserved in /history.")
    if old_id:
        okmsg(f"new thread: {new_id}   old thread: {old_id}  → /use {old_id}")
    else:
        dim(f"(conversation {new_id})")
    c.forked = False
    c._forked_from = None


def _warn_ds_pending(chat):
    """Warn that a conversation's last reply was interrupted (partial text was
    still persisted). Re-asking the same prompt resumes the finished part."""
    if chat and chat.get("reply_pending"):
        warn("Last reply was interrupted — its partial text is saved. "
             "Send the same prompt again to continue from there.")


def _print_ds_chat(chat, full):
    """Render a DeepSeek conversation (same shape as _print_conversation)."""
    flags = []
    if chat.get("thinking"):
        flags.append("think")
    if chat.get("search"):
        flags.append("search")
    suffix = f"  [{'/'.join(flags)}]" if flags else ""
    cprint(f"[bold]{chat.get('title') or '(untitled)'}[/bold]  "
           f"({chat.get('id')}){suffix}")
    _warn_ds_pending(chat)
    limit = None if full else 3
    for m in chat.get("messages") or []:
        role = m.get("role")
        if role == "user":
            cprint("\n[cyan]You:[/cyan]")
            _print_msg(m.get("content") or "", limit)
        elif role == "assistant":
            cprint("\n[green]DeepSeek:[/green]")
            content = m.get("content") or ""
            _print_msg(content, limit)
            _show_links(content)


def _maybe_online_ds_chat(c, cid):
    """When a chat id isn't in the local store, check the online account so
    `ds view`/`ds print` stay useful for server-side-only sessions. No model call."""
    try:
        online = {s.get("id"): s for s in (c._online_chats() or []) if s.get("id")}
    except Exception:
        online = {}
    s = online.get(cid)
    if s:
        cprint(f"[bold]{s.get('title') or '(untitled)'}[/bold]  ({cid})")
        dim("Session exists online — transcript not cached locally; "
            "use `ds sync` / `ds history` to materialize it.")
        return
    emsg(f"Conversation {cid} not found.")


def _repl_help():
    print("""
Commands:
  /help            this help
  /model <name>    switch model (see `models` / /models)
  /models          list available models
  /upload <path>   attach a file (repeat for several)
  /files           list attached files
  /clearfiles      clear attached files
  /new             start a fresh conversation
  /multi           toggle multiline input (end with a blank line)
  /status          account + current thread (session id, forked parent)
  /parent          jump back to the thread this one was forked from
  /history         list saved conversations
  /grep <pattern> [ids...] [-n N | -a]  search conversations (default: all)
  /use <id>        resume a saved conversation
  /view <id>       print a conversation + offer to save code blocks
  /download        save the code blocks from the last reply (or /download <id>)
  /print [full]    print current or given conversation (short unless 'full')
  /rename <title>  rename current conversation
  /del <id>... [-n N] [-f] delete conversations (ids or the N most recent)
  /reason [auto|thinking|fast]  reasoning mode (no arg cycles)
  /save <path>     export conversation to .md — /save <id> [path] exports a stored chat
  /token           show stored token (masked)
  /exit, /quit     leave
  /run <cmd> [--net] [--timeout N]   run sandboxed and feed the result to Qwen
  /agent <task>   start the autonomous sandboxed agent loop (oracle tier)
  !<cmd>          run locally in your shell (no sandbox, no policy)
    Anything else is sent to Qwen. Enter a blank line to start over.
""")


_remembered_shell: set[str] = set()


def _run_cmd_approve(verdict, argv):
    """Approval callback for sandbox.run(): interpreters always prompt,
    mutators prompt once per session (remembered), oracle auto-runs."""
    line = sandbox.cmdline(argv)
    if verdict.klass == sandbox.INTERPRETER:
        warn(f"[interpreter] {line}")
        dim(f"  ({verdict.reason}) — code execution")
        return ask_yes_no("Allow", False)
    if verdict.klass == sandbox.MUTATOR:
        if line in _remembered_shell:
            return True
        warn(f"[mutator] {line}")
        dim(f"  ({verdict.reason})")
        ok = ask_yes_no("Allow (remembered for this session)", True)
        if ok:
            _remembered_shell.add(line)
        return ok
    return True


def _run_shell(cmd):
    """Run a command from a REPL line prefixed with '!'. Only the local user
    can type it, so it runs unsandboxed in the real shell — no sandbox, no
    policy. `raw ` prefix kept for backwards compatibility (no-op)."""
    if cmd.startswith("raw "):
        cmd = cmd[4:].strip()
    try:
        proc = subprocess.Popen(cmd, shell=True,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                text=True, bufsize=1)
    except OSError as e:
        emsg(f"could not start shell: {e}")
        return
    try:
        for line in proc.stdout:
            print(line, end="")
        proc.wait()
    except KeyboardInterrupt:
        try:
            proc.kill()
        except OSError:
            pass
        print()
        dim("interrupted")
    if proc.returncode:
        dim(f"exit code: {proc.returncode}")


def _show_result(res):
    """Print a sandbox result dict."""
    if res["stdout"]:
        print(res["stdout"], end="")
    if res["stderr"]:
        sys.stdout.write(res["stderr"])
        sys.stdout.flush()
    note = f"[{res['backend']}] exit {res['exit_code']} in {res['duration']}s"
    if res["truncated"]:
        note += " | output truncated"
    if res["exit_code"]:
        dim(note)
    else:
        okmsg(note)


def _run_cmd_feed(cmd, workspace=None, network=False,
                  timeout_s=sandbox.DEFAULT_TIMEOUT if sandbox else 30,
                  max_out=sandbox.DEFAULT_MAX_OUT if sandbox else 262144):
    """Execute a command for /run, returning (status, text) where text is the
    combined output. status is 'ok' | 'declined' | 'denied' | 'error'."""
    try:
        argv = sandbox.parse(cmd)
    except ValueError as e:
        return "error", f"parse error: {e}"
    try:
        res = sandbox.run(argv=argv, workspace=workspace, network=network,
                          timeout_s=timeout_s, max_out=max_out,
                          approve=_run_cmd_approve)
    except PermissionError as e:
        return "declined", str(e)
    except sandbox.SandboxError as e:
        return "denied", str(e)
    out = (res.get("stdout") or "") + (res.get("stderr") or "")
    tag = f"### exit {res['exit_code']} [backend {res['backend']}]"
    if res.get("truncated"):
        tag += " (truncated)"
    return "ok", (tag + "\n" + out).rstrip()


def repl(client, init_title=""):
    init_readline()
    title = f"Qwen Chat — {client.model}"
    cprint(Panel.fit(title, border_style="cyan"))
    dim("Type /help for commands, /exit to quit.")
    transcript: list[tuple[str, str]] = []
    conv_title = init_title
    multiline = False
    last_reply = ""

    while True:
        prompt = _repl_prompt(client.model, conv_title,
                              reasoning=getattr(client, "reasoning", "auto"))
        if multiline:
            user = _input_multiline(prompt).strip()
        else:
            try:
                user = _prompt_input(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
        if not user:
            continue

        if user.startswith("!"):
            _run_shell(user[1:].strip())
            continue

        if user.startswith("/"):
            cmd, _, arg = user[1:].partition(" ")
            arg = arg.strip()
            if cmd in ("exit", "quit"):
                break
            elif cmd == "multi":
                multiline = not multiline
                okmsg(f"Multiline input {'on' if multiline else 'off'} — "
                      f"{'end with a blank line.' if multiline else ''}")
            elif cmd == "help":
                _repl_help()
            elif cmd == "model":
                if not arg:
                    warn(f"Current model: {client.model}")
                else:
                    client.model = arg
                    okmsg(f"Switched to {arg}")
            elif cmd == "models":
                for m in client.list_models():
                    cprint(m)
            elif cmd == "upload":
                if not arg:
                    emsg("usage: /upload <path>")
                    continue
                try:
                    info = client.upload_file(arg)
                    okmsg(f"Attached {arg} → {info.get('id', '?')}")
                except QwenError as e:
                    emsg(str(e))
            elif cmd == "files":
                if not client.attachments:
                    dim("No files attached.")
                else:
                    for a in client.attachments:
                        print(f"  {a['file_id']}  {a['name']}  ({a['size']} B)")
            elif cmd == "clearfiles":
                client.attachments.clear()
                okmsg("Cleared attachments.")
            elif cmd == "new":
                client.new_chat()
                conv_title = ""
                okmsg(f"New conversation: {client._chat_id}")
            elif cmd == "status":
                cmd_status(argparse.Namespace(), client)
                dim(f"session id: {client._chat_id or 'new (not yet saved)'}")
                if client._parent_chat_id:
                    dim(f"parent id:  {client._parent_chat_id}  (→ /parent)")
                dim(f"Tokens used this session: {client.tokens_used}")
            elif cmd == "reason":
                opt = arg.strip().lower()
                cycle = {"auto": "thinking", "thinking": "fast", "fast": "auto"}
                if not opt:
                    client.reasoning = cycle.get(client.reasoning, "auto")
                elif opt in ("a", "auto"):
                    client.reasoning = "auto"
                elif opt in ("t", "thinking", "think"):
                    client.reasoning = "thinking"
                elif opt in ("f", "fast"):
                    client.reasoning = "fast"
                else:
                    emsg("usage: /reason [auto|thinking|fast] (no arg cycles)")
                    continue
                okmsg(f"Reasoning: {client.reasoning}")
            elif cmd == "history":
                cmd_history(argparse.Namespace(full=arg.strip().lower() in ("full", "all")))
            elif cmd == "use":
                if not arg:
                    emsg("usage: /use <chat_id>")
                    continue
                try:
                    data = client.use_chat(arg)
                    conv_title = data.get("title") or ""
                    client._parent_chat_id = None
                    okmsg(f"Resumed: {data.get('title') or '(untitled)'}")
                except QwenError as e:
                    emsg(str(e))
            elif cmd == "parent":
                parent = client._parent_chat_id
                if not parent:
                    warn("No forked parent — this is a root thread.")
                    continue
                try:
                    data = client.use_chat(parent)
                    client._parent_chat_id = None
                    conv_title = data.get("title") or ""
                    okmsg(f"Back to parent: {data.get('title') or '(untitled)'}")
                except QwenError as e:
                    emsg(str(e))
            elif cmd == "view":
                if not arg:
                    emsg("usage: /view <chat_id>")
                    continue
                cmd_view(argparse.Namespace(chat_id=arg))
            elif cmd == "download":
                # /download          -> save code blocks from the last reply
                # /download <id>     -> save every code block in a chat
                if arg:
                    try:
                        data = client.get_chat(arg)
                    except QwenError as e:
                        emsg(str(e))
                        continue
                    if not data or not data.get("id"):
                        emsg(f"Conversation {arg} not found.")
                        continue
                    label = f"qwen-{arg}"
                    msgs = data.get("chat", {}).get("messages", [])
                    blocks = _dl_chat_blocks({"messages": msgs}, _msg_answer)
                    _offer_download_blocks(label, blocks)
                elif last_reply:
                    label = f"qwen-{client._chat_id}" if client._chat_id else "qwen-live"
                    _offer_download_blocks(label, _dl_blocks_text(last_reply))
                else:
                    emsg("No reply yet. Send a message or use /download <chat_id>.")
            elif cmd == "print":
                parts = arg.split()
                if parts and parts[0].lower() in ("full", "true", "1", "y"):
                    full = True
                    rest = parts[1:]
                else:
                    full = False
                    rest = parts
                cid = rest[0] if rest else client._chat_id
                if not cid:
                    emsg("No conversation yet. Send a message or use /use <id>, "
                         "or /print full <id>.")
                    continue
                try:
                    data = client.get_chat(cid)
                except QwenError as e:
                    emsg(str(e))
                    continue
                if not data or not data.get("id"):
                    emsg(f"Conversation {cid} not found.")
                    continue
                _print_conversation(data, full)
                if full:
                    _offer_chat_code_saves(cid, data)
            elif cmd == "rename":
                if not arg:
                    emsg("usage: /rename <title>")
                elif client._chat_id:
                    client.rename_chat(client._chat_id, arg)
                    conv_title = arg
                    okmsg("Renamed.")
                else:
                    emsg("No conversation yet — send a message first.")
            elif cmd == "grep":
                spec = _grep_parse(arg.split())
                if spec.get("pattern") is None:
                    emsg("usage: /grep <pattern> [chat_id ...] [-n N] [-a] [-i]")
                    continue
                _grep_run(client.list_chats, client.get_chat, _grep_qwen_text, spec)
            elif cmd == "del":
                spec = _parse_del_spec(arg.split())
                if not spec["ids"] and not spec["last"]:
                    emsg("usage: /del <chat_id> [<chat_id> ...] [-n N] [-f]")
                    continue
                ids, force = _del_targets(client.list_chats, spec)
                if not ids:
                    emsg("Nothing to delete.")
                    continue
                _, _, active_gone = _bulk_delete(
                    ids, client.delete_chat,
                    active_id=getattr(client, "_chat_id", None), force=force)
                if active_gone:
                    client._chat_id = None
                    conv_title = ""
            elif cmd == "save":
                # /save          -> export the current conversation to .md
                # /save <path>   -> same, explicit path
                # /save <id> [path] -> export a stored conversation to .md
                save_parts = arg.split()
                saved_chat = None
                if save_parts:
                    try:
                        saved_chat = client.get_chat(save_parts[0])
                    except QwenError:
                        saved_chat = None
                if saved_chat and saved_chat.get("id"):
                    chat_id = save_parts[0]
                    path = save_parts[1] if len(save_parts) > 1 else f"{chat_id}.md"
                    title = saved_chat.get("title") or chat_id
                    msgs = saved_chat.get("chat", {}).get("messages", [])
                    doc = _conversation_to_md(title, msgs, _msg_answer)
                    _save_md(path, doc)
                    okmsg(f"Saved conversation {chat_id} to {path}")
                else:
                    # No explicit chat id: prefer the live conversation (fetch
                    # the full stored chat when we've resumed/created one) over
                    # the in-memory transcript, which stays empty after /use.
                    path = arg or f"qwen-transcript-{time.strftime('%Y%m%d-%H%M%S')}.md"
                    cur = None
                    if client._chat_id:
                        try:
                            cur = client.get_chat(client._chat_id)
                        except QwenError:
                            cur = None
                    if cur and cur.get("id"):
                        title = cur.get("title") or client._chat_id
                        msgs = cur.get("chat", {}).get("messages", [])
                        if msgs:
                            doc = _conversation_to_md(title, msgs, _msg_answer)
                            _save_md(path, doc)
                            okmsg(f"Saved conversation {client._chat_id} to {path}")
                        else:
                            _save_transcript(transcript, path)
                            okmsg(f"Saved to {path}")
                    else:
                        _save_transcript(transcript, path)
                        okmsg(f"Saved to {path}")
            elif cmd == "token":
                cmd_token(argparse.Namespace())
            elif cmd == "agent":
                if not arg:
                    emsg("usage: /agent <task...>")
                    continue
                if agent_mod is None:
                    emsg("agent.py not found next to qwen.py.")
                    continue
                task = arg
                okmsg(f"starting agent loop (tier=oracle) — chat {client._chat_id}")
                try:
                    res = agent_mod.agent_loop(
                        client, task,
                        tier="oracle", workspace=os.getcwd(),
                        workspace_ro=False, max_steps=12, timeout_s=30,
                        interactive=True, on_result=_agent_progress,
                        log_path=None)
                except agent_mod.AgentError as e:
                    emsg(str(e))
                    continue
                print()
                if res["status"] == "done":
                    okmsg(f"Done in {res['steps']} steps ({res['duration']}s)")
                    if res["summary"]:
                        dim(f"summary: {res['summary']}")
                else:
                    warn(f"Reached the step cap without ```done```.")
            elif cmd == "run":
                if not arg:
                    emsg("usage: /run <cmd> [--net] [--timeout N]")
                    continue
                if sandbox is None:
                    emsg("sandbox.py not available — cannot /run")
                    continue
                network = False
                timeout_s = sandbox.DEFAULT_TIMEOUT
                tokens = arg.split()
                kept = []
                i = 0
                while i < len(tokens):
                    t = tokens[i]
                    if t == "--net":
                        network = True
                    elif t == "--timeout":
                        try:
                            timeout_s = int(tokens[i + 1])
                            i += 1
                        except (IndexError, ValueError):
                            emsg("--timeout needs a number")
                            timeout_s = sandbox.DEFAULT_TIMEOUT
                    else:
                        kept.append(t)
                    i += 1
                cmd_text = " ".join(kept).strip()
                if not cmd_text:
                    emsg("usage: /run <cmd> [--net] [--timeout N]")
                    continue
                status, feed = _run_cmd_feed(
                    cmd_text, workspace=os.getcwd(), network=network,
                    timeout_s=timeout_s)
                if status == "declined":
                    dim(f"declined: {cmd_text}")
                    continue
                if status != "ok":
                    emsg(feed)
                    continue
                user = (f"I ran the command: {cmd_text}\n"
                        f"(network: {'on' if network else 'off'})\n\n"
                        f"Sandboxed output:\n\n{feed}")
                transcript.append(("user", user))
                cprint("[cyan]Qwen:[/cyan]")
                try:
                    full, usage, chat_id = client.stream_chat(
                        user, on_delta=_stream_write,
                        on_reason=_make_reason_writer())
                    print()
                except QwenError as e:
                    emsg(str(e))
                    transcript.pop()
                    continue
                transcript.append(("assistant", full))
                last_reply = full
                _dl_hint(full)
                if usage:
                    dim(f"({usage.get('total_tokens', '?')} tokens | "
                        f"chat {chat_id or 'new'})")
            else:
                warn(f"Unknown command /{cmd}. Try /help.")
            continue

        transcript.append(("user", user))
        cprint("[cyan]Qwen:[/cyan]")
        try:
            full, usage, chat_id = client.stream_chat(
                user, on_delta=_stream_write, on_reason=_make_reason_writer())
            print()
        except QwenError as e:
            emsg(str(e))
            transcript.pop()
            continue
        transcript.append(("assistant", full))
        last_reply = full
        _dl_hint(full)
        if usage:
            dim(f"({usage.get('total_tokens', '?')} tokens | chat {chat_id or 'new'})")
        if not conv_title and client._chat_id:
            try:
                cur = client.get_chat(client._chat_id)
                conv_title = (cur or {}).get("title") or ""
            except QwenError:
                conv_title = ""


def _offer_ds_code_saves(c, chat_id):
    """Offer to save code blocks from a DeepSeek conversation (like /view)."""
    chat = c.get_chat(chat_id)
    if not chat:
        return
    blocks = []
    for m in chat.get("messages") or []:
        if m.get("role") == "assistant":
            blocks.extend(_extract_code_blocks(m.get("content") or ""))
    if not blocks:
        return
    sess_dir = os.path.join(os.getcwd(), chat_id)
    os.makedirs(sess_dir, exist_ok=True)
    cprint(f"\n[bold yellow]>>> {len(blocks)} code block(s) — saving to {sess_dir}"
           f"[/bold yellow]")
    for i, b in enumerate(blocks, 1):
        default = b["filename"] or f"block_{i}.{_lang_ext(b['lang'])}"
        _preview_block(i, b, default)
        try:
            inp = input(f"  save block {i} as [{default}]? "
                        f"(Enter=save, 'n'=skip, or path): ")
        except EOFError:
            break
        except KeyboardInterrupt:
            print()
            dim("skipped the rest")
            break
        s = inp.strip()
        if s.lower() in ("n", "no"):
            continue
        if not s:
            path = os.path.join(sess_dir, default)
        elif os.path.isabs(s) or s.startswith("/"):
            path = s
        else:
            path = os.path.join(sess_dir, s)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(b["content"])
            okmsg(f"  saved -> {os.path.abspath(path)}")
        except OSError as ex:
            emsg(f"  could not write {path}: {ex}")


def _preview_block(i, block, default):
    lines = block["content"].splitlines()
    total = len(lines)
    shown = lines[:8]
    dim(f"  --- preview of block {i} ({default}, {total} lines) ---")
    for ln in shown:
        _console.print(f"      {ln}", highlight=False) if _RICH else print(f"      {ln}")
    if total > 8:
        dim(f"      ... {total - 8} more line(s)")


def _dl_base():
    """Base directory for /download — QWEN_DL_DIR env, else ./downloads."""
    return os.environ.get("QWEN_DL_DIR", os.path.join(os.getcwd(), "downloads"))


def _dl_safe_name(name):
    """Turn an arbitrary chat id / label into a clean directory name."""
    clean = re.sub(r"[^\w.-]+", "_", name).strip("._") or "chat"
    return clean


def _dl_unique_path(dest_dir, name):
    """Return a path under dest_dir for `name`, adding _1, _2 ... on clashes."""
    base, ext = os.path.splitext(name)
    cand = os.path.join(dest_dir, name)
    i = 1
    while os.path.exists(cand):
        cand = os.path.join(dest_dir, f"{base}_{i}{ext}")
        i += 1
    return cand


def _dl_blocks_text(text):
    """Shortcut: count / extract code blocks from a raw reply."""
    return _extract_code_blocks(text)


def _dl_chat_blocks(chat, render):
    """Collect every code block across an assistant's messages in a chat."""
    blocks = []
    for m in chat.get("messages") or []:
        if m.get("role") == "assistant":
            blocks.extend(_extract_code_blocks(render(m)))
    return blocks


def _offer_download_blocks(label, blocks, dest_dir=None):
    """Batch-save code blocks with a single prompt. Returns how many saved.

    Accepts at the prompt: Enter/yes/all, a comma list like 1,3,6, or no/0 to
    skip. Files go to dest_dir (default ./downloads/<label>/), each written
    only if its name doesn't collide (a _n suffix is added otherwise)."""
    if not blocks:
        dim("No code blocks to download.")
        return 0
    if dest_dir is None:
        dest_dir = os.path.join(_dl_base(), _dl_safe_name(label))
    os.makedirs(dest_dir, exist_ok=True)
    cprint(f"\n[bold cyan]>>> {len(blocks)} code block(s) from {label!r}[/bold cyan]")
    for i, b in enumerate(blocks, 1):
        n = b["content"].count("\n") + 1
        name = (b.get("filename") or "").replace(" ", "_") or f"block_{i}.{_lang_ext(b['lang'])}"
        cprint(f"  {i:2d}. {name:<28} ({n} line(s))", highlight=False)
    try:
        sel = input(f"  save to {dest_dir}?  [Enter=all | 1,3,6 | no] ")
    except (EOFError, KeyboardInterrupt):
        print()
        return 0
    s = sel.strip().lower()
    if s in ("", "y", "yes", "all", "*"):
        want = list(range(1, len(blocks) + 1))
    elif s in ("n", "no", "0", "q", "quit", "skip"):
        dim(f"  skipped ({label})")
        return 0
    else:
        want = []
        for part in s.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                try:
                    a, b = part.split("-")
                    want.extend(range(int(a), int(b) + 1))
                    continue
                except ValueError:
                    pass
            try:
                want.append(int(part))
            except ValueError:
                pass
        want = sorted({i for i in want if 1 <= i <= len(blocks)})
        if not want:
            dim("  nothing matched — skipped.")
            return 0
    saved = 0
    for i in want:
        b = blocks[i - 1]
        name = (b.get("filename") or "").replace(" ", "_") or f"block_{i}.{_lang_ext(b['lang'])}"
        path = _dl_unique_path(dest_dir, name)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(b["content"])
        except OSError as ex:
            emsg(f"  could not write {path}: {ex}")
            continue
        okmsg(f"  saved -> {os.path.abspath(path)}")
        saved += 1
    return saved


def _dl_hint(full):
    """Print a quiet hint when a reply contains saveable code blocks."""
    n = len(_extract_code_blocks(full))
    if n:
        dim(f"({n} code block(s) — type /download to save)")

# Language name → file extension, and the set of file extensions we treat as
# code for caption/filename detection. Kept broad so any common language a
# reply might fence (ps1, rb, pl, kt, swift, rs, lua, go, ...) gets a matching
# save name instead of blockN.<ext>.
_LANG_TO_EXT = {
    "python": "py", "python3": "py", "py": "py", "bash": "sh", "shell": "sh",
    "sh": "sh", "zsh": "zsh", "powershell": "ps1", "ps1": "ps1", "pwsh": "ps1",
    "cmd": "cmd", "batch": "bat", "bat": "bat", "javascript": "js", "js": "js",
    "node": "js", "typescript": "ts", "ts": "ts", "html": "html", "htm": "html",
    "css": "css", "json": "json", "json5": "json5", "sql": "sql", "yaml": "yml",
    "yml": "yml", "jinja2": "j2", "jinja": "j2", "ruby": "rb", "rb": "rb",
    "go": "go", "golang": "go", "rust": "rs", "rs": "rs", "java": "java",
    "kotlin": "kt", "kt": "kt", "c": "c", "h": "h", "cpp": "cpp", "c++": "cpp",
    "cxx": "cpp", "cc": "cc", "hpp": "hpp", "csharp": "cs", "cs": "cs",
    "fsharp": "fs", "fs": "fs", "php": "php", "lua": "lua", "perl": "pl",
    "pl": "pl", "r": "r", "swift": "swift", "objective-c": "m", "objc": "m",
    "m": "m", "scala": "scala", "scala3": "scala", "dart": "dart",
    "elixir": "ex", "ex": "ex", "exs": "exs", "erlang": "erl", "erl": "erl",
    "clojure": "clj", "clj": "clj", "haskell": "hs", "hs": "hs", "ml": "ml",
    "ocaml": "ml", "v": "v", "zig": "zig", "nim": "nim", "r": "r",
    "smali": "smali", "assembly": "asm", "asm": "asm", "s": "s",
    "vb": "vb", "vb.net": "vb", "visualbasic": "vb", "powershell_ps1": "ps1",
    "dockerfile": "Dockerfile", "makefile": "mk", "make": "mk",
    "markdown": "md", "md": "md", "text": "txt", "txt": "txt",
    "xml": "xml", "svg": "svg", "toml": "toml", "ini": "ini", "env": "env",
}

# Extensions we treat as savable code/script files for caption-detection.
_CODE_EXTS = ("py", "sh", "zsh", "bash", "ps1", "psm1", "rb", "pl", "pm",
              "js", "jsx", "ts", "tsx", "html", "htm", "css", "scss", "json",
              "json5", "sql", "yml", "yaml", "j2", "jinja", "go", "rs", "java",
              "kt", "kts", "c", "h", "cpp", "cc", "cxx", "hpp", "cs", "fs",
              "php", "lua", "pl", "r", "swift", "m", "scala", "dart", "groovy",
              "clj", "cljs", "el", "elm", "ex", "exs", "erl", "lfe", "hs",
              "ml", "v", "zig", "nim", "smali", "asm", "s", "vb", "vbnet",
              "bat", "psh", "fish", "coffee", "tsx", "vue", "svelte", "rbw",
              "gemspec", "rake", "erb", "haml", "slim", "ipynb", "tf", "hcl",
              "tfvars", "proto", "graphql", "gql", "md", "markdown", "rst",
              "adoc", "tex", "txt", "log", "xml", "svg", "toml", "ini", "cfg",
              "conf", "env", "properties", "dockerfile", "make", "mk", "cmake",
              "pyc", "wasm")


def _lang_ext(lang):
    return _LANG_TO_EXT.get(lang.lower(), lang.lower() or "txt")


def _caption_filename(before):
    probe = before.rstrip()
    if "\n" in probe:
        probe = probe.rsplit("\n", 1)[-1]
        if probe.strip().startswith("```"):
            probe = probe.rsplit("\n", 1)[-1]
    ext_alt = "|".join(_CODE_EXTS)
    for m in re.finditer(rf"`([A-Za-z0-9_.-]+\.(?:{ext_alt}))`", probe, re.I):
        return m.group(1)
    for m in re.finditer(rf"[\w./-]+\.(?:{ext_alt})\b", probe, re.I):
        return m.group(0)
    return ""


_KNOWN_LANGS = set(_LANG_TO_EXT) | {
    "json5", "shell", "bash", "zsh", "golang", "objc", "objective-c",
    "visualbasic", "vb.net", "scala3", "markdown", "jinja", "jinja2",
}

_EXT_RE = re.compile(r"^[\w./-]+\.(?P<ext>[A-Za-z0-9]{1,10})$")


def _extract_code_blocks(text):
    blocks = []
    pat = re.compile(r"```([^\n]*)\n(.*?)```", re.S)
    for m in pat.finditer(text):
        words = m.group(1).strip().split()
        lang = ""
        fname = ""
        for w in words:
            wl = w.lower()
            if not lang and wl in _KNOWN_LANGS:
                lang = wl
                continue
            if not fname and _EXT_RE.match(w) and len(w) <= 96:
                fname = w
        # No filename token found: if the first word itself looks like a file
        # (e.g. ```greet.py), treat it as the filename and derive the language
        # from its extension.
        if not fname and words and _EXT_RE.match(words[0]):
            fname = words[0]
        if not lang and words and _EXT_RE.match(words[0]):
            lang = _EXT_RE.match(words[0]).group("ext").lower()
        if not fname:
            fname = _caption_filename(text[:m.start()])
        blocks.append({"lang": lang or "txt", "filename": fname,
                       "content": m.group(2).rstrip("\n")})
    return blocks


_LINK_SKIP_DOMAINS = {
    "deepseek.com", "chat.deepseek.com", "www.deepseek.com",
    "chat.qwen.ai", "qwen.com", "t.co",
}


def _extract_urls(text):
    """Pull URLS out of a reply: markdown links, bare links, and http(s)
    tokens already wrapped in <>. Returns de-duplicated, in-order list of
    (url, label) where label is the visible text when present."""
    pat = re.compile(r"""
        \[(?P<label>[^\]]+)\]\((?P<md>[^)\s]+)\)   # markdown [t](u)
        |<(?P<ang>https?://[^>\s]+)>               # <http://...>
        |(?P<bare>https?://[^\s)\]]+)              # bare http(s) url
    """, re.X)
    out: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for m in pat.finditer(text):
        url = (m.group("md") or m.group("ang") or m.group("bare")).strip().rstrip(",.;:!?)")
        if not url:
            continue
        if not url.lower().startswith(("http://", "https://")):
            continue
        try:
            host = url.lower().split("/")[2].split(":")[0]
        except (IndexError, ValueError):
            host = ""
        if host in _LINK_SKIP_DOMAINS:
            continue
        if url in seen:
            continue
        label = m.group("label") if m.group("label") else None
        seen.add(url)
        out.append((url, label))
    return out


def _show_links(text):
    """Print any downloadable links found in text (used after DS replies).
    URLs are shown raw so they can be selected/copied; the markdown label is
    shown only as a parenthetical when present."""
    links = _extract_urls(text)
    if not links:
        return
    if len(links) == 1:
        url, label = links[0]
        line = url if not label else f"{url}   ({label})"
        cprint(f"[bold cyan]→[/bold cyan] {line}" if _RICH else f"→ {line}")
        return
    cprint(f"[bold cyan]→ {len(links)} links:[/bold cyan]")
    for i, (url, label) in enumerate(links, 1):
        line = url if not label else f"{url}   ({label})"
        cprint(f"  {i}. {line}" if _RICH else f"  {i}. {line}")


def _conversation_to_md(title, messages, render_text):
    """Render a full conversation into a Markdown document.

    messages: list of {"role": ..., ...} dicts; render_text(m) returns the
    plain-text content for a message. Code fences inside the content are kept
    as-is so they stay valid in the exported .md."""
    parts = [f"# {title or 'Chat conversation'}"]
    for m in messages:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        text = render_text(m)
        if not text:
            continue
        name = "You" if role == "user" else "Assistant"
        parts.append(f"\n## {name}\n\n{text}\n")
    return "\n".join(parts)


def _save_md(path, doc):
    Path(path).write_text(doc, encoding="utf-8")


def _save_transcript(transcript, path):
    """Legacy helper: export an in-memory (role, text) transcript to .md."""
    title = f"Qwen transcript — {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"
    msgs = [{"role": role, "content": text} for role, text in transcript]
    _save_md(path, _conversation_to_md(
        title, msgs, lambda m: m.get("content") or ""))


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(
        prog="qwen.py",
        description="Terminal client for chat.qwen.ai",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--dl-dir", default=None,
                        help="base directory for /download (default: ./downloads)")
    parser.add_argument("-c", "--continue", dest="continue_", action="store_true",
                        default=argparse.SUPPRESS,
                        help="resume the most recent conversation instead of starting a new one")
    sub = parser.add_subparsers(dest="command")

    p_login = sub.add_parser("login", help="login / capture a session")
    p_login.add_argument("--browser", action="store_true",
                         help="open a browser to log in & capture the session (recommended)")
    p_login.add_argument("--token", help="JWT from localStorage at chat.qwen.ai")
    p_login.add_argument("--cookie", help='cookie header string, e.g. --cookie "a=1; b=2" (headless)')
    p_login.add_argument("--capture-file", help="load a saved chat request spec JSON")
    p_login.add_argument("--email")
    p_login.add_argument("--password")

    sub.add_parser("token", help="show stored token (masked)")
    sub.add_parser("status", help="account, quota and usage")
    sub.add_parser("models", help="list models")
    p_history = sub.add_parser("history", help="list saved conversations (last 12)")
    p_history.add_argument("-f", "--full", action="store_true",
                           help="list all saved conversations")

    p_grep = sub.add_parser("grep", help="search saved conversations (one, or all)")
    p_grep.add_argument("pattern", help="regular expression to search for")
    p_grep.add_argument("chat_id", nargs="*", metavar="chat_id",
                        help="conversation(s) to search (default: all)")
    p_grep.add_argument("-n", "--last", type=int, default=None,
                        help="search the N most recent conversations")
    p_grep.add_argument("-a", "--all", action="store_true",
                        help="search every conversation")
    p_grep.add_argument("-i", "--ignore-case", action="store_true",
                        help="case-insensitive matching")
    sub.add_parser("new", help="start a fresh conversation")
    p_use = sub.add_parser("use", help="resume a conversation")
    p_use.add_argument("chat_id")
    p_del = sub.add_parser("del", help="delete conversations (ids or -n N)")
    p_del.add_argument("chat_id", nargs="*")
    p_del.add_argument("-n", "--last", type=int, default=None,
                       help="delete the N most recent conversations")
    p_del.add_argument("-f", "--force", action="store_true",
                       help="skip the bulk-delete confirmation")
    sub.add_parser("logout", help="logout and clear stored token")

    p_ask = sub.add_parser("ask", help="one-shot question")
    p_ask.add_argument("message", nargs="?", help="your question")
    p_ask.add_argument("-m", "--model", default=None, help="model to use")
    p_ask.add_argument("-u", "--upload", action="append", metavar="PATH",
                       help="attach a file (repeatable)")
    p_ask.add_argument("--no-stream", action="store_true", help="disable streaming output")
    p_ask.add_argument("--reasoning", choices=("auto", "thinking", "fast"),
                       default=None, help="reasoning mode (default: env QWEN_REASONING or auto)")

    # DeepSeek via the local Deepseek-API proxy (`python app.py` in Deepseek-API/).
    p_ds = sub.add_parser("ds", help="talk to DeepSeek via the local proxy")
    p_ds.add_argument("sub", nargs="?", default="ask",
                      help="action: ask, chat, models, history, sync, new, use, view, print, del, grep ")
    p_ds.add_argument("rest", nargs="*", default=[],
                      help="chat id (for use/view/del/grep) or your question (for ask)")
    p_ds.add_argument("-m", "--model", default=None,
                      help=f"model to use (default: {DEFAULT_MODEL})")
    p_ds.add_argument("--thinking", action="store_true", default=argparse.SUPPRESS,
                      help="enable DeepThink (defaults to the thread's state)")
    p_ds.add_argument("--search", action="store_true", default=argparse.SUPPRESS,
                      help="enable web search (defaults to the thread's state)")
    p_ds.add_argument("--no-stream", action="store_true", help="disable streaming output")
    p_ds.add_argument("-u", "--upload", action="append", metavar="PATH",
                      help="attach a file before asking (repeatable)")
    p_ds.add_argument("-n", "--last", type=int, default=None,
                      help="delete the N most recent (del) or search the N most recent (grep)")
    p_ds.add_argument("-f", "--force", action="store_true",
                      help="skip the bulk-delete confirmation (with the del action)")
    p_ds.add_argument("-a", "--all", action="store_true",
                      help="search every conversation (with the grep action)")
    p_ds.add_argument("-i", "--ignore-case", action="store_true",
                      help="case-insensitive matching (with the grep action)")
    p_ds.add_argument("-b", "--base-url", default=None,
                      help="proxy base URL (default: $DEEPSEEK_BASE_URL or http://localhost:8000)")
    p_ds.add_argument("-c", "--continue", dest="continue_ds", action="store_true",
                      default=argparse.SUPPRESS,
                      help="resume the most recent DeepSeek conversation into the REPL")

    p_chat = sub.add_parser("chat", help="interactive REPL (default)")
    p_chat.add_argument("-c", "--continue", dest="continue_", action="store_true",
                        default=argparse.SUPPRESS,
                        help="resume the most recent conversation instead of starting a new one")
    p_chat.add_argument("--reasoning", choices=("auto", "thinking", "fast"),
                        default=None, help="reasoning mode (default: env QWEN_REASONING or auto)")

    p_view = sub.add_parser("view", help="print a saved conversation's messages")
    p_view.add_argument("chat_id")

    p_print = sub.add_parser("print", help="print a conversation (short unless --full)")
    p_print.add_argument("chat_id")
    p_print.add_argument("--full", action="store_true",
                        help="print every message in full (default: first lines only)")

    p_sb = sub.add_parser("sandbox", help="sandbox backend diagnostics")
    p_sb.add_argument("--check", action="store_true",
                      help="verify policy + backend and print the active mode")
    p_sb.add_argument("--list", action="store_true",
                      help="print the loaded policy tables")

    p_run = sub.add_parser("run", help="run a command in the sandbox (headless)")
    p_run.add_argument("run_args", nargs=argparse.REMAINDER,
                       help="command line to run (argv, no shell)")
    p_run.add_argument("--net", action="store_true",
                       help="allow network access in the sandbox")
    p_run.add_argument("--timeout", type=int,
                       default=(sandbox.DEFAULT_TIMEOUT if sandbox else 30))
    p_run.add_argument("--workspace", default=os.getcwd(),
                       help="directory to bind read-write (default: cwd)")
    p_run.add_argument("--max-out", type=int,
                       default=(sandbox.DEFAULT_MAX_OUT if sandbox else 262144))
    p_run.add_argument("--sandbox", choices=["bwrap", "docker", "restricted"],
                       help="force a backend (restricted = weak, argv-only)")

    p_agent = sub.add_parser("agent", help="autonomous sandboxed agent loop")
    p_agent.add_argument("task", nargs=argparse.REMAINDER, metavar="TASK...",
                         help="task for the agent to complete")
    p_agent.add_argument("-t", "--tier", choices=["oracle", "mutator", "interpreter"],
                         default="oracle",
                         help="approval tier (default: oracle = read-only auto)")
    p_agent.add_argument("--workspace", default=os.getcwd(),
                         help="directory to work on (default: cwd)")
    p_agent.add_argument("--workspace-ro", action="store_true",
                         help="mount workspace read-only (writes fail)")
    p_agent.add_argument("--steps", type=int, default=agent_mod.DEFAULT_STEPS if agent_mod else 12,
                         help="max command steps before giving up")
    p_agent.add_argument("--timeout", type=int, default=30,
                         help="per-command timeout in seconds")
    p_agent.add_argument("--max-out", type=int,
                         default=(sandbox.DEFAULT_MAX_OUT if sandbox else 262144),
                         help="max captured output bytes per command")
    p_agent.add_argument("--sandbox", choices=["bwrap", "docker", "restricted"],
                         help="force a backend (restricted = weak, argv-only)")
    p_agent.add_argument("--allow-interpreters", action="store_true",
                         help="allow the interpreter tier (arbitrary code exec) "
                              "— dangerous, requires explicit opt-in")
    p_agent.add_argument("-l", "--log", default=None,
                         help="write a redacted transcript to this file")

    args = parser.parse_args()
    if getattr(args, "dl_dir", None):
        os.environ["QWEN_DL_DIR"] = args.dl_dir
    cmd = args.command or "chat"

    if cmd == "login":
        cmd_login(args)
    elif cmd == "token":
        cmd_token(args)
    elif cmd == "status":
        cmd_status(args)
    elif cmd == "models":
        cmd_models(args)
    elif cmd == "history":
        cmd_history(args)
    elif cmd == "new":
        cmd_new(args)
    elif cmd == "use":
        cmd_use(args)
    elif cmd == "view":
        cmd_view(args)
    elif cmd == "del":
        cmd_delete(args)
    elif cmd == "grep":
        cmd_grep(args)
    elif cmd == "logout":
        QwenClient().logout()
        okmsg("Logged out.")
    elif cmd == "ask":
        cmd_ask(args)
    elif cmd == "print":
        cmd_print(args)
    elif cmd == "sandbox":
        cmd_sandbox(args)
    elif cmd == "run":
        cmd_run(args)
    elif cmd == "agent":
        cmd_agent(args)
    elif cmd == "ds":
        cmd_ds(args)
    else:
        client = QwenClient()
        if getattr(args, "reasoning", None):
            client.reasoning = args.reasoning
        if not client.token:
            if _has_display():
                warn("Not logged in. Run `qwen.py login` first — or press Ctrl+C.")
                try:
                    if ask_yes_no("Open the login wizard now?", True):
                        _login_wizard(client)
                except KeyboardInterrupt:
                    print()
                    return
                if not client.token:
                    return
            else:
                warn("No token stored and no display available (headless).")
                warn("Store a session with: qwen.py login --cookie '<header>' [--token <JWT>]")
                return
        if getattr(args, "continue_", False):
            last = _latest_chat_id()
            if last:
                try:
                    data = client.use_chat(last)
                    okmsg(f"Resumed last conversation {last} — "
                          f"{data.get('title') or '(untitled)'}")
                    repl(client, init_title=data.get("title") or "")
                    return
                except QwenError as e:
                    emsg(str(e))
            else:
                warn("-c: no saved conversations to resume — starting a new one.")
        repl(client)


def _login_wizard(client):
    print("\n=== Qwen login ===")
    print("(1) Log in with a browser (recommended — lets chat work)")
    print("(2) Email + password")
    print("(3) Paste a JWT token from chat.qwen.ai")
    try:
        choice = input("Choose [1/2/3]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if choice == "1":
        try:
            token = login_with_browser()
            client.token = token
        except QwenError as e:
            emsg(str(e))
    elif choice == "2":
        email = input("Email: ").strip()
        pwd = getpass("Password: ")
        try:
            client.signin(email, pwd)
            okmsg("Logged in and token stored.")
            warn("Password login gives a token only. For chat, also run `qwen.py login --browser`.")
        except QwenError as e:
            emsg(str(e))
    elif choice == "3":
        tok = getpass("Token (pasted input is hidden): ").strip()
        if tok:
            set_token(tok)
            client.token = tok
            okmsg("Token stored.")
            warn("Chat needs browser cookies. Run `qwen.py login --browser` for chat.")
        else:
            emsg("Empty token.")
    else:
        emsg("Invalid choice.")
    dim("Browser login: a Chromium window opens; log in and let it self-close once captured.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        sys.exit(130)
    except QwenError as e:
        emsg(str(e))
        sys.exit(1)
