"""SQLite-backed store for AI-generated improvement suggestions.

Suggestions are created by review jobs (via the critic or panel agent) and
optionally applied to plan versions. The store supports filtering by applied
state, minimum confidence threshold, and parent job ID.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from hermes_assistant.suggestions.model import Suggestion

_COLUMNS = (
    "id, text, confidence, applied, parent_job_id, "
    "created_at, applied_at, plan_id, plan_version"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS suggestions (
    id            TEXT PRIMARY KEY,
    text          TEXT NOT NULL,
    confidence    REAL NOT NULL DEFAULT 0.5,
    applied       INTEGER NOT NULL DEFAULT 0,
    parent_job_id TEXT,
    created_at    TEXT NOT NULL,
    applied_at    TEXT,
    plan_id       TEXT,
    plan_version  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_suggestions_job
    ON suggestions (parent_job_id);
CREATE INDEX IF NOT EXISTS idx_suggestions_applied
    ON suggestions (applied);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SuggestionNotFoundError(KeyError):
    """Raised when an operation targets a non-existent suggestion id."""


class SuggestionStore:
    """Persistent store for AI-generated improvement suggestions.

    ``":memory:"`` is accepted as db_path for isolated in-process tests.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _row_to_suggestion(self, row: sqlite3.Row) -> Suggestion:
        return Suggestion(
            id=row["id"],
            text=row["text"],
            confidence=row["confidence"],
            applied=bool(row["applied"]),
            parent_job_id=row["parent_job_id"],
            created_at=row["created_at"],
            applied_at=row["applied_at"],
            plan_id=row["plan_id"],
            plan_version=row["plan_version"],
        )

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def add(
        self,
        text: str,
        confidence: float,
        *,
        parent_job_id: str | None = None,
    ) -> Suggestion:
        """Create and persist a new suggestion."""
        s = Suggestion(text=text, confidence=confidence, parent_job_id=parent_job_id)
        self._conn.execute(
            f"INSERT INTO suggestions ({_COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                s.id, s.text, s.confidence, int(s.applied),
                s.parent_job_id, s.created_at, s.applied_at,
                s.plan_id, s.plan_version,
            ),
        )
        self._conn.commit()
        return s

    def apply(
        self,
        suggestion_id: str,
        *,
        plan_id: str | None = None,
        plan_version: int | None = None,
    ) -> Suggestion:
        """Mark a suggestion as applied, optionally linking to a plan version.

        Raises ``SuggestionNotFoundError`` if not found.
        """
        s = self.get(suggestion_id)
        if s is None:
            raise SuggestionNotFoundError(suggestion_id)
        now = _now()
        self._conn.execute(
            "UPDATE suggestions SET applied=1, applied_at=?, plan_id=?, plan_version=? "
            "WHERE id=?",
            (now, plan_id, plan_version, suggestion_id),
        )
        self._conn.commit()
        result = self.get(suggestion_id)
        assert result is not None
        return result

    def unapply(self, suggestion_id: str) -> Suggestion:
        """Undo an application, clearing applied, applied_at, plan_id, plan_version."""
        s = self.get(suggestion_id)
        if s is None:
            raise SuggestionNotFoundError(suggestion_id)
        self._conn.execute(
            "UPDATE suggestions SET applied=0, applied_at=NULL, "
            "plan_id=NULL, plan_version=NULL WHERE id=?",
            (suggestion_id,),
        )
        self._conn.commit()
        result = self.get(suggestion_id)
        assert result is not None
        return result

    def link_job(self, suggestion_id: str, job_id: str) -> Suggestion:
        """Associate a suggestion with a job ID after the fact."""
        s = self.get(suggestion_id)
        if s is None:
            raise SuggestionNotFoundError(suggestion_id)
        self._conn.execute(
            "UPDATE suggestions SET parent_job_id=? WHERE id=?",
            (job_id, suggestion_id),
        )
        self._conn.commit()
        result = self.get(suggestion_id)
        assert result is not None
        return result

    def delete(self, suggestion_id: str) -> bool:
        """Remove a suggestion; returns True if deleted."""
        cur = self._conn.execute(
            "DELETE FROM suggestions WHERE id=?", (suggestion_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get(self, suggestion_id: str) -> Suggestion | None:
        """Fetch a suggestion by id; returns None if not found."""
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM suggestions WHERE id=?", (suggestion_id,)
        ).fetchone()
        return self._row_to_suggestion(row) if row else None

    def list(
        self,
        *,
        applied: bool | None = None,
        min_confidence: float | None = None,
        parent_job_id: str | None = None,
    ) -> list[Suggestion]:
        """Return suggestions matching the given filters, newest first."""
        where_clauses: list[str] = []
        params: list[object] = []
        if applied is not None:
            where_clauses.append("applied = ?")
            params.append(int(applied))
        if min_confidence is not None:
            where_clauses.append("confidence >= ?")
            params.append(min_confidence)
        if parent_job_id is not None:
            where_clauses.append("parent_job_id = ?")
            params.append(parent_job_id)
        where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM suggestions {where} ORDER BY created_at DESC",
            params,
        ).fetchall()
        return [self._row_to_suggestion(r) for r in rows]

    # ------------------------------------------------------------------
    # Scoring helper
    # ------------------------------------------------------------------

    @staticmethod
    def score(text: str) -> float:
        """Compute a heuristic confidence score for a suggestion text.

        Longer, more specific suggestions score higher. Used when the LLM
        does not return an explicit confidence value.
        Returns a value in [0.0, 1.0].
        """
        words = text.split()
        n = len(words)
        if n == 0:
            return 0.0
        # Base score from word count (saturates at 50 words → 0.9)
        base = min(n / 50, 0.9)
        # Boost for action words that suggest concrete fixes
        action_words = {
            "add", "remove", "update", "fix", "clarify", "define",
            "document", "specify", "include", "ensure",
        }
        boost = sum(0.02 for w in words if w.lower() in action_words)
        return min(base + boost, 1.0)
