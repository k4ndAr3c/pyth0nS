#!/usr/bin/env python3
"""
deepseek_client.py - talk to DeepSeek through the local Deepseek-API proxy.

The proxy (repo "Deepseek-API", run as `python app.py`) turns your signed-in
chat.deepseek.com session into an OpenAI-compatible HTTP API on
http://localhost:8000/v1. This module is a tiny, dependency-free client for
that proxy — used by qwen.py's `ds` command:

    qwen.py ds ask "hello"
    qwen.py ds chat              # interactive REPL
    qwen.py ds models
    qwen.py ds history           # list saved conversations
    qwen.py ds new               # start a fresh conversation
    qwen.py ds use <chat_id>     # resume a saved conversation
    qwen.py ds del <chat_id>     # delete a saved conversation

It supports SSE streaming, model selection, DeepThink (`thinking`), web
`search`, and multi-turn threads via the proxy's `conversation_id` field.
"""

from __future__ import annotations

import json
import os
import sys
import time

import requests

DEFAULT_BASE = os.environ.get("DEEPSEEK_BASE_URL", "http://localhost:8000")
DEFAULT_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

KNOWN_MODELS = ("deepseek-chat", "deepseek-expert")


class DeepSeekError(Exception):
    pass


def _cid_key(conversation_id: str) -> str:
    """Stable chat id (the session uuid) from a '<session_uuid>:<msg_id>' token."""
    if not conversation_id:
        return ""
    return conversation_id.split(":", 1)[0]


class ConversationStore:
    """File-backed storage for DeepSeek conversations.

    The proxy keeps threads alive via `conversation_id` but exposes no
    list/get/delete API, so /history, /use, /view, /print, /rename and /del in
    the DeepSeek REPL are served from this store. Threads are persisted after
    each exchange and resumed via their session uuid.
    """

    def __init__(self, path: str):
        self._path = path

    def _load(self) -> dict:
        try:
            return json.loads(open(self._path).read())
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        tmp = self._path + ".tmp"
        with open(tmp, "w") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2))
        os.replace(tmp, self._path)

    def list(self) -> list:
        chats = self._load()
        out = [c for c in chats.values() if isinstance(c, dict)]
        out.sort(key=lambda c: c.get("updated_at", 0), reverse=True)
        return out

    def get(self, chat_id: str) -> dict | None:
        return self._load().get(chat_id)

    def save(self, chat: dict) -> None:
        data = self._load()
        data[chat["id"]] = chat
        self._save(data)

    def delete(self, chat_id: str) -> bool:
        data = self._load()
        if chat_id in data:
            del data[chat_id]
            self._save(data)
            return True
        return False


class DeepSeekSession:
    """A multi-turn conversation against the proxy."""

    def __init__(self, base_url: str = DEFAULT_BASE, model: str = DEFAULT_MODEL,
                 store_path: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.conversation_id: str | None = None
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        if store_path is None:
            store_path = os.environ.get(
                "DEEPSEEK_STORE",
                os.path.join(os.path.expanduser("~"), ".config", "qwen-cli",
                             "deepseek-chats.json"))
        self.store = ConversationStore(store_path)
        # In-memory transcript of the live thread (used by /view & /print).
        self.log: list[dict] = []

    # -- low level -------------------------------------------------------- #
    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _check_base(self) -> None:
        try:
            r = self._session.get(self._url("/healthz"), timeout=5)
        except requests.RequestException as e:
            raise DeepSeekError(
                f"Cannot reach the DeepSeek proxy at {self.base_url} "
                f"({e}). Start it with: python app.py   (in Deepseek-API/)")
        if r.status_code != 200:
            raise DeepSeekError(
                f"DeepSeek proxy unhealthy ({r.status_code}).")

    def list_models(self) -> list[str]:
        """Return model names advertised by the proxy's /v1/models."""
        try:
            r = self._session.get(self._url("/v1/models"), timeout=10)
            r.raise_for_status()
            data = r.json().get("data", [])
            return [m["id"] for m in data if isinstance(m, dict)]
        except (requests.RequestException, ValueError) as e:
            raise DeepSeekError(f"Could not list models: {e}")

    def _body(self, prompt: str, *, thinking: bool, search: bool, stream: bool) -> dict:
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": stream,
            "thinking": thinking,
            "search": search,
        }
        if self.conversation_id:
            body["conversation_id"] = self.conversation_id
        return body

    # -- conversation persistence ------------------------------------------ #
    def _record(self, prompt: str, reply: str) -> None:
        self.log.append({"role": "user", "content": prompt})
        self.log.append({"role": "assistant", "content": reply})
        self._persist()

    def _persist(self) -> None:
        cid = self.conversation_id or ""
        key = _cid_key(cid)
        if not key or not self.log:
            return
        now = int(time.time())
        chat = self.store.get(key) or {
            "id": key, "title": self.log[0]["content"][:60] or "(untitled)",
            "created_at": now,
        }
        chat["updated_at"] = now
        chat["conversation_id"] = cid
        chat["messages"] = self.log
        chat["model"] = self.model
        self.store.save(chat)

    def new_conversation(self) -> None:
        self.conversation_id = None
        self.log = []

    def save_chat(self, title: str | None = None) -> str:
        """Persist the current thread under a title, returning its chat id."""
        from uuid import uuid4
        key = _cid_key(self.conversation_id) or uuid4().hex
        now = int(time.time())
        chat = self.store.get(key) or {"id": key, "created_at": now}
        chat.update({
            "title": title or (self.log[0]["content"][:60] if self.log else "(untitled)"),
            "updated_at": now,
            "conversation_id": self.conversation_id or key,
            "messages": self.log,
            "model": self.model,
        })
        self.store.save(chat)
        return key

    def list_chats(self) -> list:
        return self.store.list()

    def use_chat(self, chat_id: str) -> dict:
        chat = self.store.get(chat_id)
        if not chat:
            raise DeepSeekError(f"Conversation {chat_id} not found.")
        self.conversation_id = chat.get("conversation_id") or chat_id
        self.log = list(chat.get("messages") or [])
        self.model = chat.get("model") or self.model
        return chat

    def get_chat(self, chat_id: str) -> dict | None:
        return self.store.get(chat_id)

    def rename_chat(self, chat_id: str, title: str) -> bool:
        chat = self.store.get(chat_id)
        if not chat:
            return False
        chat["title"] = title
        self.store.save(chat)
        return True

    def delete_chat(self, chat_id: str, force: bool = True) -> bool:
        return self.store.delete(chat_id)

    # -- public ------------------------------------------------------------ #
    def chat_once(self, prompt: str, *, thinking: bool = False, search: bool = False):
        """Non-streaming: return (full_text, conversation_id, usage)."""
        self._check_base()
        body = self._body(prompt, thinking=thinking, search=search, stream=False)
        try:
            r = self._session.post(self._url("/v1/chat/completions"), json=body, timeout=120)
        except requests.RequestException as e:
            raise DeepSeekError(f"Request failed: {e}")
        try:
            data = r.json()
        except ValueError:
            raise DeepSeekError(f"Proxy returned non-JSON ({r.status_code}).")
        if "error" in data:
            raise DeepSeekError(data["error"].get("message", "Unknown proxy error"))
        text = "".join(
            (c.get("message") or {}).get("content") or ""
            for c in data.get("choices", [])
        )
        cid = data.get("conversation_id")
        if cid:
            self.conversation_id = cid
        self._record(prompt, text)
        return text, cid, data.get("usage") or {}

    def stream_chat(self, prompt: str, *, thinking: bool = False, search: bool = False,
                    on_delta=None):
        """Stream a reply. Yields text deltas; returns (full, cid, usage)."""
        self._check_base()
        body = self._body(prompt, thinking=thinking, search=search, stream=True)
        try:
            r = self._session.post(
                f"{self._url('/v1/chat/completions')}", json=body,
                stream=True, timeout=(10, 300),
            )
        except requests.RequestException as e:
            raise DeepSeekError(f"Request failed: {e}")
        if r.status_code != 200:
            snippet = ""
            try:
                snippet = r.text[:200]
            except Exception:
                pass
            raise DeepSeekError(f"Proxy error ({r.status_code}): {snippet}")

        full: list[str] = []
        usage: dict = {}
        try:
            for raw in r.iter_lines(decode_unicode=True):
                if not raw:
                    continue
                line = raw.strip()
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    evt = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if evt.get("error"):
                    raise DeepSeekError(evt["error"].get("message", "stream error"))
                for ch in evt.get("choices") or []:
                    delta = ch.get("delta") or {}
                    piece = delta.get("content")
                    if isinstance(piece, str) and piece:
                        full.append(piece)
                        if on_delta:
                            on_delta(piece)
                if evt.get("conversation_id"):
                    self.conversation_id = evt["conversation_id"]
                if evt.get("usage"):
                    usage = evt["usage"]
        finally:
            r.close()
        self._record(prompt, "".join(full))
        return "".join(full), self.conversation_id, usage

    def close(self) -> None:
        self._session.close()


# --------------------------------------------------------------------------- #
# CLI (also reachable as `python -m deepseek_client` for quick one-shots)
# --------------------------------------------------------------------------- #
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        prog="deepseek_client",
        description="Talk to DeepSeek through the local Deepseek-API proxy.")
    sub = ap.add_subparsers(dest="command")

    pa = sub.add_parser("ask", help="one-shot question against the proxy")
    pa.add_argument("prompt", nargs="+", help="your question")
    pa.add_argument("-m", "--model", default=DEFAULT_MODEL)
    pa.add_argument("--thinking", action="store_true")
    pa.add_argument("--search", action="store_true")
    pa.add_argument("--no-stream", action="store_true")
    pa.add_argument("-c", "--cid", default=None, help="resume a conversation_id")

    sub.add_parser("models", help="list models the proxy advertises")

    pm = sub.add_parser("chat", help="interactive REPL")
    pm.add_argument("-m", "--model", default=DEFAULT_MODEL)

    args = ap.parse_args(argv)
    ds = DeepSeekSession(model=getattr(args, "model", DEFAULT_MODEL))

    if args.command == "models":
        for m in ds.list_models():
            print(m)
        return 0

    if args.command == "ask":
        prompt = " ".join(args.prompt)
        if args.cid:
            ds.conversation_id = args.cid
        if args.no_stream:
            text, cid, usage = ds.chat_once(
                prompt, thinking=args.thinking, search=args.search)
            print(text)
        else:
            def _w(p):
                sys.stdout.write(p)
                sys.stdout.flush()
            full, cid, usage = ds.stream_chat(
                prompt, thinking=args.thinking, search=args.search, on_delta=_w)
            print()
        if cid:
            print(f"(conversation_id: {cid})")
        return 0

    if args.command == "chat":
        print(f"DeepSeek proxy REPL — model {ds.model}. Type 'exit' to quit.")
        while True:
            try:
                prompt = input(">>> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not prompt:
                continue
            if prompt in ("exit", "quit", "/exit"):
                break
            if prompt in ("/new", "/reset"):
                ds.new_conversation()
                print("(new conversation)")
                continue
            print("[DeepSeek] ", end="", flush=True)
            full, cid, usage = ds.stream_chat(prompt, on_delta=lambda p: (
                sys.stdout.write(p), sys.stdout.flush()))
            print()
            if cid:
                print(f"(conversation_id: {cid})")
    return 0


if __name__ == "__main__":
    sys.exit(main())