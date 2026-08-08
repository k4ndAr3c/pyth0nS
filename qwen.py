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
  qwen.py ask "your question"  # one-shot question
  qwen.py status               # account, model, quota + tokens used
  qwen.py models               # list available models
  qwen.py history              # list saved conversations
  qwen.py new                  # start a fresh conversation
  qwen.py use <chat_id>        # resume a saved conversation
  qwen.py del <chat_id>        # delete a saved conversation
  qwen.py token                # show the stored token (masked)
  qwen.py logout
  qwen.py ds [ask|chat|models|history|new|use|del]
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
  /history        list saved conversations
  /use <id>       resume a saved conversation
  /rename <title> rename the current conversation
  /del <id>       delete a saved conversation
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

try:
    import deepseek_client
except ImportError:
    deepseek_client = None

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
        "status", "history", "use", "view", "print", "rename", "del", "save",
        "token", "exit", "quit",
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
        self.attachments: list[dict] = []          # uploaded file references
        self.tokens_used = 0                       # cumulative tokens this run
        self.model = DEFAULT_MODEL

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
            return body
        return body

    def stream_chat(self, user_text, on_delta=None):
        """Stream a completion, returning (full_text, usage, chat_id)."""
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
                    for ch in evt.get("choices") or []:
                        delta = (ch.get("delta") or {})
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
            self._chat_id = chat_id
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
            self._chat_id = chat_id
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

    def new_chat(self, title=""):
        # Legacy v1 endpoint is retired; v2 create is used instead.
        cid = self.create_chat()
        if title:
            try:
                self.rename_chat(cid, title)
            except QwenError:
                pass
        return {"id": cid}

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


def cmd_status(args):
    c = QwenClient()
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


def cmd_history(args):
    c = QwenClient()
    try:
        chats = c.list_chats()
    except QwenError as e:
        emsg(str(e))
        return
    if not chats:
        dim("No saved conversations.")
        return
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
    dim("\nResume with: qwen.py use <id>   or in REPL: /use <id>")


def _msg_answer(m):
    for e in (m.get("content_list") or []):
        if e.get("phase") == "answer" and e.get("content"):
            return e["content"]
    return m.get("content") or ""


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
    repl(c)


def cmd_delete(args):
    c = QwenClient()
    if args.force or ask_yes_no(f"Delete conversation {args.chat_id}?", False):
        okmsg("Deleted.") if c.delete_chat(args.chat_id) else emsg("Delete failed.")
    else:
        dim("Cancelled.")


def cmd_ask(args):
    c = QwenClient()
    if args.model:
        c.model = args.model
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
        full, usage, chat_id = c.stream_chat(text, on_delta=_stream_write)
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


def cmd_ds(args):
    """Talk to DeepSeek through the local Deepseek-API proxy (`python app.py`
    inside the Deepseek-API/ repo, which speaks OpenAI at :8000/v1)."""
    if deepseek_client is None:
        emsg("deepseek_client module not found next to qwen.py.")
        return
    base = args.base_url or None
    model = args.model or deepseek_client.DEFAULT_MODEL
    if base:
        import os
        os.environ["DEEPSEEK_BASE_URL"] = base
    c = deepseek_client.DeepSeekSession(model=model)

    if args.sub == "models":
        try:
            for m in c.list_models():
                cprint(m)
        except deepseek_client.DeepSeekError as e:
            emsg(str(e))
        finally:
            c.close()
        return

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
            ds_repl(c, args)
        except deepseek_client.DeepSeekError as e:
            emsg(str(e))
        c.close()
        return

    if args.sub == "del":
        if not args.rest or not args.rest[0]:
            emsg("usage: qwen.py ds del <chat_id>")
            c.close()
            return
        chat_id = args.rest[0]
        try:
            if c.delete_chat(chat_id):
                okmsg(f"Deleted conversation {chat_id}.")
            else:
                emsg(f"Conversation {chat_id} not found.")
        except deepseek_client.DeepSeekError as e:
            emsg(str(e))
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
            ftx, cid, usage = c.chat_once(msg, thinking=args.thinking,
                                          search=args.search)
            cprint(ftx)
        else:
            ftx, cid, usage = c.stream_chat(
                msg, thinking=args.thinking, search=args.search,
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
  /model <name>    switch model (deepseek-chat / deepseek-expert)
  /models          list available models
  /new             start a fresh conversation
  /status          current model + conversation
  /think           toggle DeepThink for subsequent messages
  /history         list saved conversations (local store)
  /use <id>        resume a saved conversation
  /view <id>       print a conversation + offer to save code blocks
  /print [full]    print current or given conversation (short unless 'full')
  /rename <title>  rename current conversation
  /del <id>        delete a saved conversation
  /save <path>     export this chat to .md — /save <id> [path] exports a stored chat
  /token           show the proxy address in use
  /exit, /quit     leave
 !<cmd>            run a shell command
Anything else is sent to DeepSeek via the local proxy.
Links appearing in replies are listed automatically below the answer.
""")


def ds_repl(c, args):
    """DeepSeek REPL — same slash commands as the Qwen REPL, backed by the
    DeepSeek session's local conversation store."""
    init_readline()
    cprint(Panel.fit(f"DeepSeek proxy REPL — {c.model}", border_style="magenta"))
    dim("Type /help for commands, /exit to quit.")

    while True:
        try:
            user = input("\n[You] ").strip()
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
            elif cmd == "help":
                _ds_repl_help()
            elif cmd == "model":
                if not arg:
                    warn(f"Current model: {c.model}")
                else:
                    c.model = arg
                    okmsg(f"Switched to {arg}")
            elif cmd == "models":
                try:
                    for m in c.list_models():
                        cprint(m)
                except deepseek_client.DeepSeekError as e:
                    emsg(str(e))
            elif cmd == "think":
                # toggle DeepThink in-session; ask/chat default off.
                args.thinking = not args.thinking
                okmsg(f"DeepThink {'on' if args.thinking else 'off'}")
            elif cmd in ("new", "reset"):
                c.new_conversation()
                okmsg("New conversation.")
            elif cmd == "status":
                dim(f"model: {c.model} | base: {c.base_url}" if _RICH
                    else f"model: {c.model}  base: {c.base_url}")
                if c.conversation_id:
                    dim(f"conversation_id: {c.conversation_id}")
                    dim(f"turns in thread: {len(c.log) // 2}")
                else:
                    dim("no conversation yet — send a message")
            elif cmd == "history":
                chats = c.list_chats()
                if not chats:
                    dim("No saved conversations.")
                    continue
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
            elif cmd == "use":
                if not arg:
                    emsg("usage: /use <chat_id>")
                    continue
                try:
                    data = c.use_chat(arg)
                    okmsg(f"Resumed: {data.get('title') or '(untitled)'}")
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
            elif cmd == "rename":
                if not arg:
                    emsg("usage: /rename <title>")
                elif c.rename_chat(_cid_key(c), arg):
                    okmsg("Renamed.")
                else:
                    emsg("No conversation to rename — send a message first.")
            elif cmd == "del":
                if not arg:
                    emsg("usage: /del <chat_id>")
                elif c.delete_chat(arg):
                    okmsg("Deleted.")
                else:
                    emsg(f"Conversation {arg} not found.")
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
            else:
                warn(f"Unknown command /{cmd}. Try /help.")
            continue

        cprint("[magenta]DeepSeek:[/magenta]")
        try:
            if args.no_stream:
                ftx, cid, usage = c.chat_once(user, thinking=args.thinking, search=args.search)
                cprint(ftx)
            else:
                ftx, cid, usage = c.stream_chat(
                    user, thinking=args.thinking, search=args.search,
                    on_delta=_stream_write)
                print()
        except deepseek_client.DeepSeekError as e:
            emsg(str(e))
            continue
        _show_links(ftx)
        _offer_code_saves(user, ftx)
        if cid:
            dim(f"(conversation {_cid_key(c)})")


def _cid_key(c):
    """Stable chat id for the current DeepSeek thread (session uuid)."""
    return (c.conversation_id or "").split(":", 1)[0]


def _print_ds_chat(chat, full):
    """Render a DeepSeek conversation (same shape as _print_conversation)."""
    cprint(f"[bold]{chat.get('title') or '(untitled)'}[/bold]  ({chat.get('id')})")
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
  /status          account + tokens used this session
  /history         list saved conversations
  /use <id>        resume a saved conversation
  /view <id>       print a conversation + offer to save code blocks
  /print [full]    print current or given conversation (truncated unless 'full')
  /rename <title>  rename current conversation
  /del <id>        delete a conversation
  /save <path>     export conversation to .md — /save <id> [path] exports a stored chat
  /token           show stored token (masked)
  /exit, /quit     leave
 !<cmd>            run a shell command
Anything else is sent to Qwen. Enter a blank line to start over.
""")


def _run_shell(cmd):
    """Run a shell command from a REPL line prefixed with '!'. Streams
    stdout/stderr live and shows the exit status when non-zero."""
    import subprocess
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


def repl(client):
    init_readline()
    title = f"Qwen Chat — {client.model}"
    cprint(Panel.fit(title, border_style="cyan"))
    dim("Type /help for commands, /exit to quit.")
    transcript: list[tuple[str, str]] = []

    while True:
        try:
            user = input("\n[You] ").strip()
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
                okmsg(f"New conversation: {client._chat_id}")
            elif cmd == "status":
                cmd_status(argparse.Namespace())
                dim(f"Tokens used this session: {client.tokens_used}")
            elif cmd == "history":
                cmd_history(argparse.Namespace())
            elif cmd == "use":
                if not arg:
                    emsg("usage: /use <chat_id>")
                    continue
                try:
                    data = client.use_chat(arg)
                    okmsg(f"Resumed: {data.get('title') or '(untitled)'}")
                except QwenError as e:
                    emsg(str(e))
            elif cmd == "view":
                if not arg:
                    emsg("usage: /view <chat_id>")
                    continue
                cmd_view(argparse.Namespace(chat_id=arg))
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
                    okmsg("Renamed.")
                else:
                    emsg("No conversation yet — send a message first.")
            elif cmd == "del":
                if not arg:
                    emsg("usage: /del <chat_id>")
                else:
                    client.delete_chat(arg)
                    okmsg("Deleted.")
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
            else:
                warn(f"Unknown command /{cmd}. Try /help.")
            continue

        transcript.append(("user", user))
        cprint("[cyan]Qwen:[/cyan]")
        try:
            full, usage, chat_id = client.stream_chat(user, on_delta=_stream_write)
            print()
        except QwenError as e:
            emsg(str(e))
            transcript.pop()
            continue
        transcript.append(("assistant", full))
        if usage:
            dim(f"({usage.get('total_tokens', '?')} tokens | chat {chat_id or 'new'})")
        _offer_code_saves(user, full)


def _offer_code_saves(user, full):
    blocks = _extract_code_blocks(full)
    if not blocks:
        return
    cprint(f"[bold green]>>> {len(blocks)} code block(s) — save as files?[/bold green]")
    for i, b in enumerate(blocks, 1):
        lang = b["lang"]
        code = b["content"]
        fname = b["filename"] or f"block{i}.{_lang_ext(lang)}"
        try:
            inp = input(f"  save block {i} as [{fname}]? (enter=save, 'n'=skip): ")
        except EOFError:
            return
        except KeyboardInterrupt:
            print()
            dim("skipped the rest")
            return
        s = inp.strip()
        if s.lower() in ("n", "no", "q"):
            dim(f"      skipped block {i}")
            continue
        path = s if s else fname
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(code)
            okmsg(f"      saved -> {os.path.abspath(path)}")
        except OSError as ex:
            emsg(f"      could not write {path}: {ex}")


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


def _preview_block(i, b, default):
    lines = b["content"].splitlines()
    total = len(lines)
    shown = lines[:8]
    dim(f"  --- preview of block {i} ({default}, {total} lines) ---")
    for ln in shown:
        _console.print(f"      {ln}", highlight=False) if _RICH else print(f"      {ln}")
    if total > 8:
        dim(f"      ... {total - 8} more line(s)")

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
    sub.add_parser("history", help="list saved conversations")
    sub.add_parser("new", help="start a fresh conversation")
    p_use = sub.add_parser("use", help="resume a conversation")
    p_use.add_argument("chat_id")
    p_del = sub.add_parser("del", help="delete a conversation")
    p_del.add_argument("chat_id")
    p_del.add_argument("-f", "--force", action="store_true")
    sub.add_parser("logout", help="logout and clear stored token")

    p_ask = sub.add_parser("ask", help="one-shot question")
    p_ask.add_argument("message", nargs="?", help="your question")
    p_ask.add_argument("-m", "--model", default=None, help="model to use")
    p_ask.add_argument("-u", "--upload", action="append", metavar="PATH",
                       help="attach a file (repeatable)")
    p_ask.add_argument("--no-stream", action="store_true", help="disable streaming output")

    # DeepSeek via the local Deepseek-API proxy (`python app.py` in Deepseek-API/).
    p_ds = sub.add_parser("ds", help="talk to DeepSeek via the local proxy")
    p_ds.add_argument("sub", nargs="?", default="ask",
                      help="action: ask, chat, models, history, new, use, del ")
    p_ds.add_argument("rest", nargs="*", default=[],
                      help="chat id (for use/del) or your question (for ask)")
    p_ds.add_argument("-m", "--model", default=None,
                      help=f"model to use (default: {DEFAULT_MODEL})")
    p_ds.add_argument("--thinking", action="store_true", help="enable DeepThink reasoning")
    p_ds.add_argument("--search", action="store_true", help="enable web search")
    p_ds.add_argument("--no-stream", action="store_true", help="disable streaming output")
    p_ds.add_argument("-u", "--base-url", default=None,
                      help="proxy base URL (default: $DEEPSEEK_BASE_URL or http://localhost:8000)")

    sub.add_parser("chat", help="interactive REPL (default)")

    p_view = sub.add_parser("view", help="print a saved conversation's messages")
    p_view.add_argument("chat_id")

    p_print = sub.add_parser("print", help="print a conversation (short unless --full)")
    p_print.add_argument("chat_id")
    p_print.add_argument("--full", action="store_true",
                        help="print every message in full (default: first lines only)")

    args = parser.parse_args()
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
    elif cmd == "logout":
        QwenClient().logout()
        okmsg("Logged out.")
    elif cmd == "ask":
        cmd_ask(args)
    elif cmd == "print":
        cmd_print(args)
    elif cmd == "ds":
        cmd_ds(args)
    else:
        client = QwenClient()
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
