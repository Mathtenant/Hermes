"""Unit tests for the Pendenz model (Phase 2.6)."""

from __future__ import annotations

from datetime import date

import pytest

from hermes_assistant.tasks.pendenzen import Pendenz, PendenzSource
from hermes_assistant.tasks.store import TaskStore


@pytest.fixture
def store() -> TaskStore:
    return TaskStore(":memory:")


def _pendenz(title: str, source: PendenzSource = PendenzSource.manual, **kwargs) -> Pendenz:
    return Pendenz(id="", title=title, source=source, **kwargs)


# --------------------------------------------------------------------------- #
# T1: Create pendenz from review finding
# --------------------------------------------------------------------------- #

def test_create_pendenz_from_review(store: TaskStore) -> None:
    """A review finding (blocker) can be turned into a pendenz with source=review."""
    p = _pendenz(
        "Fix missing risk matrix",
        source=PendenzSource.review,
        source_ref="job-abc123",
        priority="blocker",
        raised_by="critic",
    )
    pid = store.create(p)
    loaded = store.get(pid)
    assert loaded is not None
    assert loaded.node_kind == "pendenz"
    assert loaded.title == "Fix missing risk matrix"
    # Loaded as Task from store — cast back to Pendenz via model_validate.
    pendenz = Pendenz.model_validate(loaded.model_dump())
    assert pendenz.source == PendenzSource.review
    assert pendenz.source_ref == "job-abc123"
    assert pendenz.priority == "blocker"
    assert pendenz.raised_by == "critic"


def test_pendenz_node_kind_is_pendenz() -> None:
    p = _pendenz("Simple action")
    assert p.node_kind == "pendenz"


# --------------------------------------------------------------------------- #
# T2: List by source
# --------------------------------------------------------------------------- #

def test_list_by_source_filters_correctly(store: TaskStore) -> None:
    store.create(_pendenz("Review action 1", PendenzSource.review))
    store.create(_pendenz("Review action 2", PendenzSource.review))
    store.create(_pendenz("Manual action", PendenzSource.manual))

    all_tasks = store.list_by_parent(None)
    review_pendenzen = [
        t for t in all_tasks
        if t.node_kind == "pendenz"
        and Pendenz.model_validate(t.model_dump()).source == PendenzSource.review
    ]
    manual_pendenzen = [
        t for t in all_tasks
        if t.node_kind == "pendenz"
        and Pendenz.model_validate(t.model_dump()).source == PendenzSource.manual
    ]
    assert len(review_pendenzen) == 2
    assert len(manual_pendenzen) == 1


# --------------------------------------------------------------------------- #
# T3: Pendenz source enum values
# --------------------------------------------------------------------------- #

def test_all_pendenz_sources_are_valid() -> None:
    expected = {"manual", "review", "decision", "meeting", "facilitator_import"}
    actual = {s.value for s in PendenzSource}
    assert actual == expected


# --------------------------------------------------------------------------- #
# T4: Due date and priority fields
# --------------------------------------------------------------------------- #

def test_pendenz_due_date_and_priority() -> None:
    p = _pendenz(
        "Deadline task",
        source=PendenzSource.decision,
        due_date=date(2026, 9, 1),
        priority="high",
    )
    assert p.due_date == date(2026, 9, 1)
    assert p.priority == "high"
