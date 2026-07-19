"""Unit tests for meeting note capture (Phase 2.6).

Confidentiality rule: ``raw_notes`` MUST NOT appear in any exported output
(safe_dict, serialisation, or CLI-facing data).  These tests verify that
invariant in the same spirit as the ICS §29 whitelist checks.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from hermes_assistant.tasks.meetings import MeetingNote, MeetingStore, _heuristic_actions


@pytest.fixture
def mstore() -> MeetingStore:
    return MeetingStore(":memory:")


def _note(title: str = "Sprint retrospective", raw: str = "ACTION: Write tests") -> MeetingNote:
    return MeetingNote(
        title=title,
        date=date(2026, 7, 13),
        attendees=["alice", "bob"],
        raw_notes=raw,
    )


# --------------------------------------------------------------------------- #
# T1: Create and retrieve meeting note
# --------------------------------------------------------------------------- #

def test_create_and_get_meeting(mstore: MeetingStore) -> None:
    note = _note()
    mid = mstore.create(note)
    loaded = mstore.get(mid)
    assert loaded is not None
    assert loaded.title == "Sprint retrospective"
    assert loaded.attendees == ["alice", "bob"]


def test_get_unknown_returns_none(mstore: MeetingStore) -> None:
    assert mstore.get("no-such-id") is None


def test_list_meetings(mstore: MeetingStore) -> None:
    mstore.create(_note("Meeting A"))
    mstore.create(_note("Meeting B"))
    notes = mstore.list_all()
    assert len(notes) == 2


# --------------------------------------------------------------------------- #
# T2: Action extraction (heuristic fallback — no LLM)
# --------------------------------------------------------------------------- #

def test_heuristic_action_extraction() -> None:
    raw = "General discussion.\nACTION: Send report\nACTION: Schedule follow-up\nSome comment."
    actions = _heuristic_actions(raw)
    assert actions == ["Send report", "Schedule follow-up"]


def test_extract_actions_offline(mstore: MeetingStore) -> None:
    raw = "ACTION: Draft risk matrix\nNotes here.\nACTION: Update schedule"
    mid = mstore.create(_note(raw=raw))
    actions = mstore.extract_actions(mid, client=None)
    assert "Draft risk matrix" in actions
    assert "Update schedule" in actions


def test_extract_actions_persists(mstore: MeetingStore) -> None:
    mid = mstore.create(_note(raw="ACTION: Persist this"))
    mstore.extract_actions(mid, client=None)
    loaded = mstore.get(mid)
    assert loaded is not None
    assert "Persist this" in loaded.extracted_actions


def test_extract_actions_mock_llm(mstore: MeetingStore) -> None:
    """When a client is available, the LLM result replaces heuristic output."""
    mock_client = MagicMock()
    mock_client.structured.return_value = {"actions": ["LLM action 1", "LLM action 2"]}

    mid = mstore.create(_note())
    actions = mstore.extract_actions(mid, client=mock_client)
    assert actions == ["LLM action 1", "LLM action 2"]
    assert mock_client.structured.called


# --------------------------------------------------------------------------- #
# T3: Confidentiality — raw_notes never exported (§29-style whitelist)
# --------------------------------------------------------------------------- #

def test_safe_dict_excludes_raw_notes() -> None:
    note = _note(raw="CONFIDENTIAL: Board discussed acquisition target.")
    safe = note.safe_dict()
    assert "raw_notes" not in safe
    # Verify nothing resembling the raw content leaks via any value.
    for v in safe.values():
        assert "CONFIDENTIAL" not in str(v)


def test_safe_dict_includes_public_fields() -> None:
    note = _note(title="Board meeting")
    safe = note.safe_dict()
    assert safe["title"] == "Board meeting"
    assert "attendees" in safe
    assert "extracted_actions" in safe
    assert "created_at" in safe
    assert "id" in safe


def test_raw_notes_present_in_full_dump_but_excluded_via_safe() -> None:
    """Full model_dump includes raw_notes; safe_dict does not.  This ensures
    the model doesn't silently lose the field — it's intentionally excluded
    by the export path only.
    """
    note = _note(raw="Internal notes")
    full = note.model_dump()
    safe = note.safe_dict()
    assert "raw_notes" in full       # present in internal representation
    assert "raw_notes" not in safe   # absent from any export path
