"""Invariant tests for the JSON import pipeline (Phase 2d): atomicity + M2.

Core invariants:
- Partial failure within an entity-type batch writes zero rows for that
  batch (all-or-nothing) — validated in Pass 1 before any DB write in Pass 2.
- Re-importing the exact same payload is idempotent: no duplicate rows are
  created (M2). Risks/plans dedup on ``id`` (INSERT OR REPLACE / version
  bump); pendenzen dedup on ``external_ref`` with an ``id`` fallback.
"""

from __future__ import annotations

from pathlib import Path

from hermes_assistant.plans.editor import PlanEditor
from hermes_assistant.risks.registry import RiskRegistry
from hermes_assistant.tasks.store import TaskStore
from hermes_assistant.webapp.import_json import import_payload


def _paths(tmp_path: Path) -> dict[str, str]:
    return {
        "risks_db": str(tmp_path / "risks.db"),
        "plans_db": str(tmp_path / "plans.db"),
        "tasks_db": str(tmp_path / "tasks.db"),
        "projects_root": str(tmp_path / "projects"),
    }


# ---------------------------------------------------------------------------
# Atomicity — partial failure -> zero rows written
# ---------------------------------------------------------------------------


def test_risks_partial_failure_writes_zero_rows(tmp_path: Path) -> None:
    payload = {
        "risks": [
            {"title": "Valid risk"},
            {"description": "Missing title"},  # invalid: no 'title'
        ]
    }
    paths = _paths(tmp_path)
    result = import_payload(payload, **paths)

    # H5: entire batch aborted — even the valid item is not written. Only the
    # individually-invalid item is reported as skipped; the valid sibling is
    # simply never committed (created stays 0), which is the all-or-nothing
    # invariant under test.
    assert result.created == 0
    assert result.updated == 0
    assert result.skipped == 1

    reg = RiskRegistry(paths["risks_db"])
    assert reg.list() == []
    reg.close_connection()


def test_plans_partial_failure_writes_zero_versions(tmp_path: Path) -> None:
    payload = {
        "plans": [
            {"plan_id": "plan-good", "items": [{"title": "Item 1"}]},
            {"plan_id": "plan-bad", "items": [{"no_title": "oops"}]},
        ]
    }
    paths = _paths(tmp_path)
    result = import_payload(payload, **paths)

    assert result.created == 0
    assert result.updated == 0
    assert result.skipped == 1

    editor = PlanEditor(paths["plans_db"])
    assert editor.list_plans() == []
    editor.close()


def test_pendenzen_partial_failure_writes_zero_rows(tmp_path: Path) -> None:
    payload = {
        "pendenzen": [
            {"title": "Valid pendenz"},
            {"title": "Bad priority", "priority": "not-a-real-priority"},
        ]
    }
    paths = _paths(tmp_path)
    result = import_payload(payload, **paths)

    assert result.created == 0
    assert result.updated == 0
    assert result.skipped == 1

    store = TaskStore(paths["tasks_db"])
    tree = store.tree()
    assert tree.get("children", []) == []
    store.close()


def test_one_bad_entity_type_does_not_block_a_good_one(tmp_path: Path) -> None:
    """Atomicity is scoped per entity-type batch, not the whole payload:
    a failing risks batch must not prevent a valid plans batch from committing."""
    payload = {
        "risks": [{"description": "no title"}],
        "plans": [{"plan_id": "plan-ok", "items": [{"title": "Kickoff"}]}],
    }
    paths = _paths(tmp_path)
    result = import_payload(payload, **paths)

    assert result.created == 1  # the plan
    assert result.skipped == 1  # the risk

    editor = PlanEditor(paths["plans_db"])
    assert editor.get("plan-ok") is not None
    editor.close()


# ---------------------------------------------------------------------------
# M2 idempotency — re-import same JSON -> no duplicates
# ---------------------------------------------------------------------------


def test_reimport_same_risks_by_id_does_not_duplicate(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    payload = {"risks": [{"id": "fixed-risk-id", "title": "Budget overrun"}]}

    import_payload(payload, **paths)
    result2 = import_payload(payload, **paths)

    assert result2.updated == 1
    assert result2.created == 0

    reg = RiskRegistry(paths["risks_db"])
    assert len(reg.list()) == 1
    reg.close_connection()


def test_reimport_same_plan_id_bumps_version_not_duplicates_plan(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    payload = {"plans": [{"plan_id": "plan-x", "items": [{"title": "A"}]}]}

    import_payload(payload, **paths)
    import_payload(payload, **paths)

    editor = PlanEditor(paths["plans_db"])
    assert editor.list_plans() == ["plan-x"]  # still exactly one plan
    versions = editor.list_versions("plan-x")
    assert len(versions) == 2  # each import call created a new version
    editor.close()


def test_reimport_pendenzen_dedups_on_external_ref(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    payload = {"pendenzen": [{"title": "Copilot task", "external_ref": "cop-001"}]}

    r1 = import_payload(payload, **paths)
    r2 = import_payload(payload, **paths)

    assert r1.created == 1
    assert r2.created == 0
    assert r2.updated == 1

    store = TaskStore(paths["tasks_db"])
    matches = [
        n for n in store.tree().get("children", []) if n.get("title") == "Copilot task"
    ]
    assert len(matches) == 1
    store.close()


def test_reimport_full_mixed_payload_twice_is_idempotent(tmp_path: Path) -> None:
    """A realistic multi-entity payload, imported twice, must not duplicate
    any entity type."""
    paths = _paths(tmp_path)
    payload = {
        "risks": [{"id": "r-1", "title": "Risk one"}],
        "plans": [{"plan_id": "p-1", "items": [{"title": "Kickoff"}]}],
        "pendenzen": [{"title": "Task one", "external_ref": "ext-1"}],
    }

    import_payload(payload, **paths)
    import_payload(payload, **paths)

    reg = RiskRegistry(paths["risks_db"])
    assert len(reg.list()) == 1
    reg.close_connection()

    editor = PlanEditor(paths["plans_db"])
    assert editor.list_plans() == ["p-1"]
    editor.close()

    store = TaskStore(paths["tasks_db"])
    matches = [n for n in store.tree().get("children", []) if n.get("title") == "Task one"]
    assert len(matches) == 1
    store.close()
