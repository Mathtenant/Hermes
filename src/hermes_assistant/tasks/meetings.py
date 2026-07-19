"""Meeting note capture — Phase 2.6 (spec §31).

``MeetingNote`` stores meeting metadata + raw notes **locally only**.  Raw
notes MUST NOT appear in any exported/serialised output.  ``MeetingStore``
persists notes to SQLite and optionally extracts action proposals via a
grammar-constrained LLM call.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# _EXPORT_EXCLUDE is used to strip confidential fields from any export path.
_EXPORT_EXCLUDE: set[str] = {"raw_notes"}


def _now() -> datetime:
    return datetime.now(UTC)


class MeetingNote(BaseModel):
    """One meeting session captured locally.

    ``raw_notes`` is CONFIDENTIAL — it must never appear in exported output.
    Use :py:meth:`safe_dict` to get an export-safe representation.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    title: str
    date: date
    attendees: list[str] = Field(default_factory=list)
    raw_notes: str = ""          # LOCAL ONLY — never exported
    extracted_actions: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)

    def safe_dict(self) -> dict[str, Any]:
        """Return a dict that excludes confidential raw_notes."""
        return self.model_dump(exclude=_EXPORT_EXCLUDE)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    date        TEXT NOT NULL,
    blob        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""


class MeetingStore:
    """Thin SQLite wrapper for MeetingNote persistence."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def create(self, note: MeetingNote) -> str:
        """Persist a MeetingNote and return its id."""
        now = _now()
        note = note.model_copy(update={"created_at": now})
        self._conn.execute(
            "INSERT INTO meetings (id, title, date, blob, created_at) VALUES (?, ?, ?, ?, ?)",
            (note.id, note.title, note.date.isoformat(), note.model_dump_json(), now.isoformat()),
        )
        self._conn.commit()
        return note.id

    def get(self, meeting_id: str) -> MeetingNote | None:
        row = self._conn.execute(
            "SELECT blob FROM meetings WHERE id = ?", (meeting_id,)
        ).fetchone()
        return MeetingNote.model_validate_json(row["blob"]) if row else None

    def list_all(self) -> list[MeetingNote]:
        """Return all meeting notes ordered by date, newest first."""
        rows = self._conn.execute(
            "SELECT blob FROM meetings ORDER BY date DESC"
        ).fetchall()
        return [MeetingNote.model_validate_json(r["blob"]) for r in rows]

    def extract_actions(
        self,
        meeting_id: str,
        client: Any = None,
    ) -> list[str]:
        """Parse raw_notes into action proposals.

        When ``client`` (an OllamaClient) is provided, sends a structured
        prompt and returns the model's action list.  When offline/unavailable,
        falls back to a heuristic line scan (lines starting with "ACTION:").

        Raw notes are NEVER forwarded off-device; the LLM call goes to the
        local Ollama endpoint only.
        """
        note = self.get(meeting_id)
        if note is None:
            raise KeyError(f"Meeting {meeting_id!r} not found")

        actions: list[str]
        if client is not None:
            try:
                schema = {
                    "type": "object",
                    "properties": {
                        "actions": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["actions"],
                }
                result = client.structured(
                    model="",  # caller may set; client falls back to roster
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are an action-item extractor. "
                                "Extract all action items from the meeting notes as a JSON list."
                            ),
                        },
                        {"role": "user", "content": note.raw_notes},
                    ],
                    schema=schema,
                )
                actions = result.get("actions", [])
            except Exception:  # noqa: BLE001 — offline fallback
                actions = _heuristic_actions(note.raw_notes)
        else:
            actions = _heuristic_actions(note.raw_notes)

        # Persist extracted actions back to the note.
        row = self._conn.execute(
            "SELECT blob FROM meetings WHERE id = ?", (meeting_id,)
        ).fetchone()
        if row:
            existing = json.loads(row["blob"])
            existing["extracted_actions"] = actions
            self._conn.execute(
                "UPDATE meetings SET blob = ? WHERE id = ?",
                (json.dumps(existing), meeting_id),
            )
            self._conn.commit()
        return actions


def _heuristic_actions(raw_notes: str) -> list[str]:
    """Fallback: lines starting with 'ACTION:' are returned as action items."""
    actions = []
    for line in raw_notes.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("ACTION:"):
            actions.append(stripped[len("ACTION:"):].strip())
    return actions
