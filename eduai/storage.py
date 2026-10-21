"""Local SQLite storage for conversations, messages and settings.

Everything is kept in one file under data/ (git-ignored) on the student's own
computer. Nothing is uploaded anywhere.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from eduai.config import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "eduai.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    -- Increases on every change; used for ordering because clock timestamps can tie.
    activity    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id  INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role             TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content          TEXT NOT NULL,
    model            TEXT,
    stopped          INTEGER NOT NULL DEFAULT 0,  -- answer was stopped before it finished
    stats            TEXT,                        -- JSON: seconds, tokens/s, finish reason
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id);
CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
"""

TITLE_LENGTH = 60


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def make_title(first_message: str) -> str:
    text = " ".join(first_message.split())
    return text if len(text) <= TITLE_LENGTH else text[: TITLE_LENGTH - 1].rstrip() + "…"


@dataclass(frozen=True)
class Conversation:
    id: int
    title: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Message:
    id: int
    conversation_id: int
    role: str
    content: str
    model: str | None
    stopped: bool
    stats: dict | None
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)


LEGACY_DB_PATH = DATA_DIR / "edulite.db"  # name before the project became Edu.ai


def migrate_legacy_db(path: Path) -> None:
    """Keep chats from before the rename: move edulite.db (and its WAL files) to eduai.db."""
    if path != DEFAULT_DB_PATH or path.exists() or not LEGACY_DB_PATH.exists():
        return
    for suffix in ("", "-wal", "-shm"):
        old = LEGACY_DB_PATH.with_name(LEGACY_DB_PATH.name + suffix)
        if old.exists():
            old.rename(path.with_name(path.name + suffix))


class Store:
    def __init__(self, path: Path | str = DEFAULT_DB_PATH):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            migrate_legacy_db(Path(path))
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)
        self._lock = threading.Lock()

    def close(self) -> None:
        self._conn.close()

    # ---- conversations ----------------------------------------------------
    def create_conversation(self, title: str = "New chat") -> Conversation:
        now = _now()
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO conversations (title, created_at, updated_at, activity) VALUES (?, ?, ?, "
                "(SELECT COALESCE(MAX(activity), 0) + 1 FROM conversations))", (title, now, now))
        return Conversation(cur.lastrowid, title, now, now)

    def list_conversations(self) -> list[Conversation]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, title, created_at, updated_at FROM conversations ORDER BY activity DESC").fetchall()
        return [Conversation(**dict(r)) for r in rows]

    def get_conversation(self, conversation_id: int) -> Conversation | None:
        with self._lock:
            row = self._conn.execute("SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
                                     (conversation_id,)).fetchone()
        return Conversation(**dict(row)) if row else None

    def rename_conversation(self, conversation_id: int, title: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("UPDATE conversations SET title = ? WHERE id = ?",
                                     (title.strip()[:200] or "Untitled", conversation_id))
        return cur.rowcount > 0

    def delete_conversation(self, conversation_id: int) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        return cur.rowcount > 0

    # ---- messages ---------------------------------------------------------
    def add_message(self, conversation_id: int, role: str, content: str, model: str | None = None,
                    stopped: bool = False, stats: dict | None = None) -> Message:
        now = _now()
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO messages (conversation_id, role, content, model, stopped, stats, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (conversation_id, role, content, model, int(stopped), json.dumps(stats) if stats else None, now))
            self._conn.execute(
                "UPDATE conversations SET updated_at = ?, "
                "activity = (SELECT COALESCE(MAX(activity), 0) + 1 FROM conversations) WHERE id = ?",
                (now, conversation_id))
            # Name a new chat after its first question.
            if role == "user":
                self._conn.execute(
                    "UPDATE conversations SET title = ? WHERE id = ? AND title = 'New chat'",
                    (make_title(content), conversation_id))
        return Message(cur.lastrowid, conversation_id, role, content, model, stopped, stats, now)

    def messages(self, conversation_id: int) -> list[Message]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id", (conversation_id,)).fetchall()
        return [Message(r["id"], r["conversation_id"], r["role"], r["content"], r["model"], bool(r["stopped"]),
                        json.loads(r["stats"]) if r["stats"] else None, r["created_at"]) for r in rows]

    def delete_message(self, message_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))

    # ---- settings ---------------------------------------------------------
    def get_settings(self) -> dict:
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: json.loads(r["value"]) for r in rows}

    def save_settings(self, values: dict) -> None:
        with self._lock, self._conn:
            self._conn.executemany("INSERT INTO settings (key, value) VALUES (?, ?) "
                                   "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                                   [(k, json.dumps(v)) for k, v in values.items()])
