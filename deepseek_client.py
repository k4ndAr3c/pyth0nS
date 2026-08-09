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
    qwen.py ds --upload f.pdf ask "summarise"   # attach a file

It supports SSE streaming, model selection, DeepThink (`thinking`), web
`search`, file attachment (`/upload`, `--upload`, `ref_file_ids`), and
multi-turn threads via the proxy's `conversation_id` field.
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

# Friendly display names (Instant / Expert) map onto the real model ids the
# proxy understands; /model and --model accept either.
MODEL_ALIASES = {
    "instant": "deepseek-chat",
    "expert": "deepseek-expert",
}


def normalize_model(name: str) -> str:
    """Resolve a friendly model name (e.g. 'Instant', 'instant') to the real
    id the proxy accepts ('deepseek-chat'). Returns input unchanged if unknown."""
    if not name:
        return name
    return MODEL_ALIASES.get(name.strip().lower(), name.strip())


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
        # No global Content-Type: requests sets application/json for `json=`
        # bodies and the correct multipart boundary for `files=` uploads.
        if store_path is None:
            store_path = os.environ.get(
                "DEEPSEEK_STORE",
                os.path.join(os.path.expanduser("~"), ".config", "qwen-cli",
                             "deepseek-chats.json"))
        self.store = ConversationStore(store_path)
        # In-memory transcript of the live thread (used by /view & /print).
        self.log: list[dict] = []
        # Set by list_chats()/sync_chats(): True when the online account could
        # be reached (so /history is online-authoritative), False on fallback.
        self.online_ok: bool = False
        # Uploaded file references for the live thread (sent as ref_file_ids).
        self.attachments: list[dict] = []
        # File ids already handed to DeepSeek in an earlier message of this
        # thread. A continuation must not re-send them (re-attaching a file to
        # an existing node makes DeepSeek fork the conversation and reply
        # empty), so only ids not in this set go on the wire.
        self._sent_file_ids: set[str] = set()
        # File ids staged for the current (not-yet-sent) message.
        self._pending_refs: list[str] = []
        # True once a message deliberately started a fresh branch (new file
        # added to an already-started conversation); the REPL surfaces it.
        self.forked: bool = False

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

    def upload_file(self, path: str) -> dict:
        """Upload a file through the proxy and attach it to this thread.

        Returns the proxy's file info {id, file_name, file_size, status}. The
        returned id is included in the next message's `ref_file_ids`, so call
        this before `chat_once`/`stream_chat`.)
        """
        self._check_base()
        import os
        name = os.path.basename(path) or path
        try:
            f = open(path, "rb")
        except OSError as e:
            raise DeepSeekError(f"Could not read {path}: {e}")
        try:
            try:
                r = self._session.post(
                    self._url("/v1/files/upload"),
                    files={"file": (name, f)}, timeout=120,
                )
            except requests.RequestException as e:
                raise DeepSeekError(f"Upload request failed: {e}")
        finally:
            f.close()
        if r.status_code != 200:
            snippet = ""
            try:
                snippet = r.text[:200]
            except Exception:
                pass
            # DeepSeek rejects file types it doesn't know (binaries, extensionless
            # files, libc.so.6 ...). Renaming to .txt gets past the extension
            # gate — the content itself is still read. Retry once.
            if "unsupported file type" in snippet and not name.lower().endswith(".txt"):
                return self._upload_as_txt(path)
            raise DeepSeekError(f"Proxy upload error ({r.status_code}): {snippet}")
        try:
            data = r.json()
            if "error" in data:
                raise DeepSeekError(data["error"].get("message", "Unknown proxy error"))
            info = {k: data.get(k) for k in ("id", "file_name", "file_size", "status")}
        except ValueError:
            raise DeepSeekError(f"Proxy returned non-JSON ({r.status_code}).")
        self.attachments.append({
            "id": info.get("id") or "",
            "name": info.get("file_name") or name,
            "size": info.get("file_size") or os.path.getsize(path),
        })
        return info

    def _upload_as_txt(self, path: str) -> dict:
        """Re-upload `path` under a `.txt` name after DeepSeek rejects its real
        file type. Returns the same info dict as upload_file."""
        import os
        name = os.path.basename(path) or path
        txt_name = name.rsplit(".", 1)[0] + ".txt" if "." in name else name + ".txt"
        with open(path, "rb") as f:
            try:
                r = self._session.post(
                    self._url("/v1/files/upload"),
                    files={"file": (txt_name, f)}, timeout=120,
                )
            except requests.RequestException as e:
                raise DeepSeekError(f"Upload request failed: {e}")
        if r.status_code != 200:
            snippet = ""
            try:
                snippet = r.text[:200]
            except Exception:
                pass
            raise DeepSeekError(f"Proxy upload error ({r.status_code}): {snippet}")
        data = r.json()
        if "error" in data:
            raise DeepSeekError(data["error"].get("message", "Unknown proxy error"))
        info = {k: data.get(k) for k in ("id", "file_name", "file_size", "status")}
        self.attachments.append({
            "id": info.get("id") or "",
            "name": info.get("file_name") or txt_name,
            "size": info.get("file_size") or os.path.getsize(path),
        })
        return info

    def _forking_refs(self) -> list[str]:
        """New (not-yet-delivered) file ids for the next message."""
        return [a["id"] for a in self.attachments
                if a["id"] and a["id"] not in self._sent_file_ids]

    def _fork_prompt(self, prompt: str) -> str:
        """When a new file forces a fork mid-conversation, fold the prior
        transcript into the prompt so the fresh thread keeps context."""
        if not self.log:
            return prompt
        lines = []
        for m in self.log:
            role = "User" if m.get("role") == "user" else "Assistant"
            lines.append(f"{role}: {m.get('content') or ''}")
        lines.append(f"User: {prompt}")
        lines.append("Assistant:")
        return "\n\n".join(lines)

    def _body(self, prompt: str, *, thinking: bool, search: bool, stream: bool) -> dict:
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": stream,
            "thinking": thinking,
            "search": search,
        }
        refs = self._forking_refs()
        if refs:
            body["ref_file_ids"] = refs
        if self.conversation_id:
            # A file attached to an ALREADY-STARTED thread makes chat.deepseek.com
            # fork the conversation and reply on a different branch (our stream
            # comes back empty). Attach it to a fresh thread instead, seeding the
            # new branch with the prior transcript so nothing is lost.
            if refs:
                self.forked = True
                body["messages"][0]["content"] = self._fork_prompt(prompt)
                body.pop("conversation_id", None)
            else:
                body["conversation_id"] = self.conversation_id
        self._pending_refs = list(refs)
        return body

    def _mark_sent(self) -> None:
        """Call after a message is successfully accepted so its file ids are
        never re-attached to an existing node (which forks + replies empty)."""
        if self._pending_refs:
            self._sent_file_ids.update(self._pending_refs)
            self._pending_refs = []

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
        self.attachments = []
        self._sent_file_ids = set()
        self.forked = False

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

    @staticmethod
    def _norm_ts(v):
        """Normalize a timestamp (epoch ms or seconds) to integer seconds."""
        try:
            f = float(v)
        except (TypeError, ValueError):
            return v
        return int(f / 1000) if f > 1_000_000_000_000 else int(f)

    @staticmethod
    def _model_from_type(model_type) -> str:
        """Map DeepSeek's wire model_type to the public model id."""
        if model_type == "expert":
            return "deepseek-expert"
        return "deepseek-chat"

    def _online_chats(self) -> list:
        """Talk to the proxy's /v1/chats (online session list). Returns [] if
        the proxy is old or unreachable, so callers fall back to the store."""
        try:
            r = self._session.get(self._url("/v1/chats"), timeout=15)
        except requests.RequestException:
            return []
        if r.status_code != 200:
            return []
        try:
            data = (r.json() or {}).get("data") or []
            return [c for c in data if isinstance(c, dict)]
        except ValueError:
            return []

    def _sync_from_online(self, prune: bool = True) -> tuple[list, dict]:
        """Reconcile the local store against the online account.

        The online session list (chat.deepseek.com `fetch_page`, proxied as
        /v1/chats) is the source of truth for what conversations exist. Local
        entries that no longer exist online are stale (deleted in the web UI,
        or test leftovers) and get pruned; sessions online but unknown locally
        are materialized in the store so /use & /print work on them too.

        Returns (chats, summary) where summary = {pruned, added, updated}."""
        online = self._online_chats()
        summary = {"pruned": 0, "added": 0, "updated": 0}
        if not online:
            self.online_ok = False
            return self.store.list(), summary

        self.online_ok = True
        local = {c["id"]: dict(c) for c in self.store.list()}

        # Sessions online but missing locally get a minimal entry.
        for s in online:
            cid = s.get("id")
            if not cid:
                continue
            entry = local.get(cid)
            updated = self._norm_ts(s.get("updated_at"))
            created = self._norm_ts(s.get("created_at"))
            model = self._model_from_type(s.get("model_type"))
            if entry is None:
                local[cid] = {
                    "id": cid,
                    "title": s.get("title") or "(untitled)",
                    "model": model,
                    "created_at": created or updated,
                    "updated_at": updated,
                    "conversation_id": cid,
                    "messages": [],
                }
                summary["added"] += 1
            else:
                changed = False
                if s.get("title") and not entry.get("title_custom") \
                        and entry.get("title") != s["title"]:
                    entry["title"] = s["title"]
                    changed = True
                if created and not entry.get("created_at"):
                    entry["created_at"] = created
                    changed = True
                if updated and entry.get("updated_at") != updated:
                    entry["updated_at"] = updated
                    changed = True
                if not entry.get("model") or entry["model"] != model:
                    entry["model"] = model
                    changed = True
                if changed:
                    summary["updated"] += 1

        if prune:
            # Physically drop store entries that no longer exist online.
            known = {s.get("id") for s in online}
            for cid in list(local):
                if cid not in known:
                    del local[cid]
                    if self.store.delete(cid):
                        summary["pruned"] += 1

        # Persist so /use, /del, /print, /rename and titles stay consistent.
        for entry in local.values():
            entry.setdefault("messages", [])
            self.store.save(entry)

        out = list(local.values())
        out.sort(key=lambda c: c.get("updated_at", 0), reverse=True)
        return out, summary

    def list_chats(self) -> list:
        """Conversations as they exist on the online account.

        The online chat is authoritative: missing local entries are pruned and
        server-generated titles win, so /history mirrors the real account. Falls
        back to the local store (unchanged) if the proxy is unreachable."""
        chats, _ = self._sync_from_online(prune=True)
        return chats

    def sync_chats(self) -> dict:
        """Explicitly reconcile store <-> online and report what changed."""
        _, summary = self._sync_from_online(prune=True)
        return summary

    def use_chat(self, chat_id: str) -> dict:
        chat = self.store.get(chat_id)
        if not chat:
            raise DeepSeekError(f"Conversation {chat_id} not found.")
        self.conversation_id = chat.get("conversation_id") or chat_id
        self.log = list(chat.get("messages") or [])
        self.model = chat.get("model") or self.model
        self.attachments = []
        self._sent_file_ids = set()
        self.forked = False
        return chat

    def get_chat(self, chat_id: str) -> dict | None:
        return self.store.get(chat_id)

    def rename_chat(self, chat_id: str, title: str) -> bool:
        # First rename online so the change is real (and survives resync);
        # keep title_custom so a fallback to local-only doesn't resurrect the
        # old title.
        try:
            self._session.patch(
                self._url(f"/v1/chats/{chat_id}"),
                json={"title": title}, timeout=30,
            ).raise_for_status()
        except requests.RequestException as e:
            raise DeepSeekError(f"Online rename failed: {e}") from e
        chat = self.store.get(chat_id)
        if not chat:
            return True
        chat["title"] = title
        chat["title_custom"] = True
        self.store.save(chat)
        return True

    def delete_chat(self, chat_id: str, force: bool = True) -> bool:
        # Delete online first — the online account is the source of truth, so a
        # local-only delete would just be re-spawned by the next sync.
        try:
            self._session.delete(
                self._url(f"/v1/chats/{chat_id}"), timeout=30
            ).raise_for_status()
        except requests.RequestException as e:
            raise DeepSeekError(f"Online delete failed: {e}") from e
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
        self._mark_sent()
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
        self._mark_sent()
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