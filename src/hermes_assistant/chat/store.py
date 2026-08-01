"""SQLite-backed store for chat sessions, messages, and actions.

Mirrors the ``jobqueue.jobs.JobStore`` pattern: a single WAL-mode SQLite file
with a shared connection, ``busy_timeout`` to survive concurrent writers, and
``executescript`` schema bootstrapping. ``:memory:`` is accepted for tests, in
which case the single connection is the whole database for the store's life.

Unlike the job store, referential integrity matters here: messages and actions
are child rows of a session, so ``foreign_keys=ON`` plus ``ON DELETE CASCADE``
guarantee that deleting a session leaves no orphans. ``project_id`` is a plain
TEXT column — there is no projects table to reference.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .model import ChatAction, ChatMessage, ChatRole, ChatSession

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL,
    title       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS chat_actions (
    id           TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    message_id   TEXT NOT NULL,
    action_type  TEXT NOT NULL,
    params       TEXT NOT NULL DEFAULT '{}',
    result       TEXT NOT NULL DEFAULT '{}',
    executed_at  TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY(message_id) REFERENCES chat_messages(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_session
    ON chat_messages (session_id, created_at);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ChatStore:
    """A thin, typed wrapper over the chat SQLite tables."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        """Open (creating if needed) the chat database in WAL mode.

        ``:memory:`` is accepted for tests, in which case a single shared
        connection is kept open for the store's lifetime.
        """
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False mirrors RiskRegistry/PlanEditor: the FastAPI
        # chat endpoints run store calls in a worker thread (run_in_threadpool)
        # while the connection is opened on the event-loop thread.
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # RLock serialises all public method calls so that concurrent FastAPI
        # worker threads cannot interleave execute/commit sequences on the same
        # shared connection. RLock (re-entrant) is used because some public
        # methods call other public methods internally (e.g. create_session
        # calls get_session).
        self._lock = threading.RLock()
        # WAL improves concurrent read/write; busy_timeout avoids spurious
        # "database is locked" under concurrent writers. foreign_keys=ON is
        # required for the ON DELETE CASCADE rules to actually fire.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Guarded ALTER TABLE migrations for pre-existing databases.

        Each column add is wrapped so a re-run (column already present) is a
        no-op rather than an error. New deployments hit none of these because
        the base schema already has every column.
        """
        migrations = (
            "ALTER TABLE chat_sessions ADD COLUMN title TEXT",
            "ALTER TABLE chat_messages ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'",
            "ALTER TABLE chat_actions ADD COLUMN params TEXT NOT NULL DEFAULT '{}'",
            "ALTER TABLE chat_actions ADD COLUMN result TEXT NOT NULL DEFAULT '{}'",
        )
        for stmt in migrations:
            try:
                self._conn.execute(stmt)
            except sqlite3.OperationalError:
                # Column already exists — expected on every normal startup.
                pass

    # ------------------------------------------------------------------ #
    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()

    # -- row -> model converters --------------------------------------- #
    def _row_to_session(self, row: sqlite3.Row) -> ChatSession:
        return ChatSession(
            id=row["id"],
            project_id=row["project_id"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_message(self, row: sqlite3.Row) -> ChatMessage:
        return ChatMessage(
            id=row["id"],
            session_id=row["session_id"],
            role=ChatRole(row["role"]),
            content=row["content"],
            metadata=json.loads(row["metadata"]),
            created_at=row["created_at"],
        )

    def _row_to_action(self, row: sqlite3.Row) -> ChatAction:
        return ChatAction(
            id=row["id"],
            session_id=row["session_id"],
            message_id=row["message_id"],
            action_type=row["action_type"],
            params=json.loads(row["params"]),
            result=json.loads(row["result"]),
            executed_at=row["executed_at"],
        )

    # -- sessions ------------------------------------------------------- #
    def create_session(
        self, project_id: str, title: str | None = None
    ) -> ChatSession:
        """Insert a new session and return it."""
        with self._lock:
            session_id = uuid.uuid4().hex
            now = _now()
            self._conn.execute(
                "INSERT INTO chat_sessions "
                "(id, project_id, title, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, project_id, title, now, now),
            )
            self._conn.commit()
            got = self.get_session(session_id)
            assert got is not None  # just inserted
            return got

    def get_session(self, session_id: str) -> ChatSession | None:
        """Fetch a session by id, or ``None`` if it does not exist."""
        with self._lock:
            row = self._conn.execute(
                "SELECT id, project_id, title, created_at, updated_at "
                "FROM chat_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            return self._row_to_session(row) if row is not None else None

    def list_sessions(self, project_id: str | None = None) -> list[ChatSession]:
        """List sessions (optionally filtered by project), newest first."""
        with self._lock:
            if project_id is None:
                rows = self._conn.execute(
                    "SELECT id, project_id, title, created_at, updated_at "
                    "FROM chat_sessions ORDER BY updated_at DESC"
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT id, project_id, title, created_at, updated_at "
                    "FROM chat_sessions WHERE project_id = ? "
                    "ORDER BY updated_at DESC",
                    (project_id,),
                ).fetchall()
            return [self._row_to_session(r) for r in rows]

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and (via cascade) its messages and actions.

        Returns ``True`` if a session was deleted, ``False`` if none matched.
        """
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM chat_sessions WHERE id = ?", (session_id,)
            )
            self._conn.commit()
            return cur.rowcount > 0

    def touch_session(self, session_id: str) -> None:
        """Bump a session's ``updated_at`` to now."""
        with self._lock:
            self._conn.execute(
                "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
                (_now(), session_id),
            )
            self._conn.commit()

    # -- messages ------------------------------------------------------- #
    def add_message(
        self,
        session_id: str,
        role: ChatRole,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> ChatMessage:
        """Insert a message and return it. Also touches the parent session."""
        with self._lock:
            message_id = uuid.uuid4().hex
            now = _now()
            self._conn.execute(
                "INSERT INTO chat_messages "
                "(id, session_id, role, content, metadata, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    message_id,
                    session_id,
                    ChatRole(role).value,
                    content,
                    json.dumps(metadata or {}),
                    now,
                ),
            )
            self._conn.execute(
                "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT id, session_id, role, content, metadata, created_at "
                "FROM chat_messages WHERE id = ?",
                (message_id,),
            ).fetchone()
            return self._row_to_message(row)

    def list_messages(self, session_id: str) -> list[ChatMessage]:
        """List a session's messages ordered oldest-first by ``created_at``."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, session_id, role, content, metadata, created_at "
                "FROM chat_messages WHERE session_id = ? "
                "ORDER BY created_at ASC, id ASC",
                (session_id,),
            ).fetchall()
            return [self._row_to_message(r) for r in rows]

    # -- actions -------------------------------------------------------- #
    def add_action(
        self,
        session_id: str,
        message_id: str,
        action_type: str,
        params: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
    ) -> ChatAction:
        """Insert an action row and return it."""
        with self._lock:
            action_id = uuid.uuid4().hex
            now = _now()
            self._conn.execute(
                "INSERT INTO chat_actions "
                "(id, session_id, message_id, action_type, params, result, executed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    action_id,
                    session_id,
                    message_id,
                    action_type,
                    json.dumps(params or {}),
                    json.dumps(result or {}),
                    now,
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT id, session_id, message_id, action_type, params, result, "
                "executed_at FROM chat_actions WHERE id = ?",
                (action_id,),
            ).fetchone()
            return self._row_to_action(row)

    def list_actions(self, session_id: str) -> list[ChatAction]:
        """List a session's actions ordered oldest-first by ``executed_at``."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, session_id, message_id, action_type, params, result, "
                "executed_at FROM chat_actions WHERE session_id = ? "
                "ORDER BY executed_at ASC, id ASC",
                (session_id,),
            ).fetchall()
            return [self._row_to_action(r) for r in rows]
