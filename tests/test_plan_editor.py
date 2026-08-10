"""Unit tests for PlanEditor — CRUD, versioning, diff, reorder (Phase 3a).

Complements ``tests/test_invariants_plans.py`` (which focuses on the
immutability invariant) with exhaustive coverage of every public method,
including error paths (PlanNotFoundError / PlanVersionNotFoundError) and
diff-generation edge cases (added/removed/changed/reordered).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_assistant.plans.editor import (
    PlanEditor,
    PlanNotFoundError,
    PlanVersionNotFoundError,
)
from hermes_assistant.plans.model import PlanItem, PlanItemStatus, PlanVersion


def _editor(tmp_path: Path) -> PlanEditor:
    return PlanEditor(tmp_path / "plans.db")


def _mem() -> PlanEditor:
    return PlanEditor(":memory:")


# ---------------------------------------------------------------------------
# create()
# ---------------------------------------------------------------------------


def test_create_returns_plan_version(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    pv = editor.create("plan-a", [PlanItem(title="Kickoff")])
    assert isinstance(pv, PlanVersion)
    editor.close()


def test_create_is_version_1(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    pv = editor.create("plan-a", [PlanItem(title="Kickoff")])
    assert pv.version == 1
    editor.close()


def test_create_stores_author(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    pv = editor.create("plan-a", [PlanItem(title="Kickoff")], author="alice")
    assert pv.author == "alice"
    editor.close()


def test_create_default_author_empty(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    pv = editor.create("plan-a", [PlanItem(title="Kickoff")])
    assert pv.author == ""
    editor.close()


def test_create_with_empty_items_list(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    pv = editor.create("plan-empty", [])
    assert pv.items == []
    editor.close()


def test_create_second_plan_id_starts_its_own_version_1(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    editor.create("plan-a", [PlanItem(title="A")])
    editor.update("plan-a", [PlanItem(title="A"), PlanItem(title="B")])
    pv_b = editor.create("plan-b", [PlanItem(title="X")])
    assert pv_b.version == 1
    editor.close()


# ---------------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------------


def test_get_missing_plan_returns_none(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    assert editor.get("nonexistent") is None
    editor.close()


def test_get_missing_version_returns_none(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    editor.create("plan-a", [PlanItem(title="A")])
    assert editor.get("plan-a", version=99) is None
    editor.close()


def test_get_no_version_returns_latest(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    editor.create("plan-a", [PlanItem(title="v1")])
    editor.update("plan-a", [PlanItem(title="v2")])
    latest = editor.get("plan-a")
    assert latest is not None
    assert latest.version == 2
    assert latest.items[0].title == "v2"
    editor.close()


def test_get_specific_version_after_multiple_updates(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    editor.create("plan-a", [PlanItem(title="v1")])
    editor.update("plan-a", [PlanItem(title="v2")])
    editor.update("plan-a", [PlanItem(title="v3")])
    v2 = editor.get("plan-a", version=2)
    assert v2 is not None
    assert v2.items[0].title == "v2"
    editor.close()


# ---------------------------------------------------------------------------
# update()
# ---------------------------------------------------------------------------


def test_update_missing_plan_raises(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    with pytest.raises(PlanNotFoundError):
        editor.update("nosuchplan", [PlanItem(title="X")])
    editor.close()


def test_update_bumps_version_by_one(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    editor.create("plan-a", [PlanItem(title="v1")])
    pv2 = editor.update("plan-a", [PlanItem(title="v2")])
    assert pv2.version == 2
    editor.close()


def test_update_returns_new_plan_version_instance(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    editor.create("plan-a", [PlanItem(title="v1")])
    updated = editor.update("plan-a", [PlanItem(title="v2")], author="bob")
    assert isinstance(updated, PlanVersion)
    assert updated.author == "bob"
    editor.close()


# ---------------------------------------------------------------------------
# reorder()
# ---------------------------------------------------------------------------


def test_reorder_missing_plan_raises(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    with pytest.raises(PlanNotFoundError):
        editor.reorder("nosuchplan", ["id1", "id2"])
    editor.close()


def test_reorder_with_unknown_item_id_is_ignored(tmp_path: Path) -> None:
    """item_ids referencing ids that don't exist in the latest version are
    silently skipped rather than raising."""
    editor = _editor(tmp_path)
    a = PlanItem(title="A", order=0)
    editor.create("plan-a", [a])
    reordered = editor.reorder("plan-a", ["does-not-exist", a.id])
    assert [i.title for i in reordered.items] == ["A"]
    editor.close()


def test_reorder_with_empty_item_ids_appends_all_in_original_order(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    a = PlanItem(title="A", order=0)
    b = PlanItem(title="B", order=1)
    editor.create("plan-a", [a, b])
    reordered = editor.reorder("plan-a", [])
    assert [i.title for i in reordered.items] == ["A", "B"]
    editor.close()


def test_reorder_partial_list_appends_remainder(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    a = PlanItem(title="A", order=0)
    b = PlanItem(title="B", order=1)
    c = PlanItem(title="C", order=2)
    editor.create("plan-a", [a, b, c])
    reordered = editor.reorder("plan-a", [c.id])
    assert [i.title for i in reordered.items] == ["C", "A", "B"]
    editor.close()


def test_reorder_updates_item_order_field(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    a = PlanItem(title="A", order=0)
    b = PlanItem(title="B", order=1)
    editor.create("plan-a", [a, b])
    reordered = editor.reorder("plan-a", [b.id, a.id])
    assert reordered.items[0].order == 0
    assert reordered.items[1].order == 1
    editor.close()


# ---------------------------------------------------------------------------
# delete()
# ---------------------------------------------------------------------------


def test_delete_existing_plan_returns_true(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    editor.create("plan-a", [PlanItem(title="A")])
    assert editor.delete("plan-a") is True
    assert editor.get("plan-a") is None
    editor.close()


def test_delete_missing_plan_returns_false(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    assert editor.delete("nonexistent") is False
    editor.close()


def test_delete_removes_all_versions(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    editor.create("plan-a", [PlanItem(title="v1")])
    editor.update("plan-a", [PlanItem(title="v2")])
    editor.delete("plan-a")
    assert editor.list_versions("plan-a") == []
    editor.close()


# ---------------------------------------------------------------------------
# list_versions() / list_plans()
# ---------------------------------------------------------------------------


def test_list_versions_empty_for_unknown_plan(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    assert editor.list_versions("nosuchplan") == []
    editor.close()


def test_list_versions_oldest_first(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    editor.create("plan-a", [PlanItem(title="v1")])
    editor.update("plan-a", [PlanItem(title="v2")])
    editor.update("plan-a", [PlanItem(title="v3")])
    versions = editor.list_versions("plan-a")
    assert [v.version for v in versions] == [1, 2, 3]
    editor.close()


def test_list_plans_returns_distinct_ids_sorted(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    editor.create("plan-b", [PlanItem(title="X")])
    editor.create("plan-a", [PlanItem(title="Y")])
    editor.update("plan-a", [PlanItem(title="Y2")])
    assert editor.list_plans() == ["plan-a", "plan-b"]
    editor.close()


def test_list_plans_empty_store(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    assert editor.list_plans() == []
    editor.close()


# ---------------------------------------------------------------------------
# diff()
# ---------------------------------------------------------------------------


def test_diff_missing_from_version_raises(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    editor.create("plan-a", [PlanItem(title="v1")])
    with pytest.raises(PlanVersionNotFoundError):
        editor.diff("plan-a", 99, 1)
    editor.close()


def test_diff_missing_to_version_raises(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    editor.create("plan-a", [PlanItem(title="v1")])
    with pytest.raises(PlanVersionNotFoundError):
        editor.diff("plan-a", 1, 99)
    editor.close()


def test_diff_added_items(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    a = PlanItem(title="A")
    editor.create("plan-a", [a])
    editor.update("plan-a", [a, PlanItem(title="B")])
    d = editor.diff("plan-a", 1, 2)
    assert [i.title for i in d.added] == ["B"]
    assert d.removed == []
    editor.close()


def test_diff_removed_items(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    a = PlanItem(title="A")
    b = PlanItem(title="B")
    editor.create("plan-a", [a, b])
    editor.update("plan-a", [a])
    d = editor.diff("plan-a", 1, 2)
    assert [i.title for i in d.removed] == ["B"]
    assert d.added == []
    editor.close()


def test_diff_changed_items(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    a = PlanItem(title="A", status=PlanItemStatus.open)
    editor.create("plan-a", [a])
    a_done = a.model_copy(update={"status": PlanItemStatus.done})
    editor.update("plan-a", [a_done])
    d = editor.diff("plan-a", 1, 2)
    assert len(d.changed) == 1
    old_item, new_item = d.changed[0]
    assert old_item.status is PlanItemStatus.open
    assert new_item.status is PlanItemStatus.done
    editor.close()


def test_diff_reordered_flag_true_when_order_changes(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    a = PlanItem(title="A")
    b = PlanItem(title="B")
    editor.create("plan-a", [a, b])
    editor.update("plan-a", [b, a])
    d = editor.diff("plan-a", 1, 2)
    assert d.reordered is True
    editor.close()


def test_diff_reordered_flag_false_when_order_unchanged(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    a = PlanItem(title="A")
    b = PlanItem(title="B")
    editor.create("plan-a", [a, b])
    editor.update("plan-a", [a, b])
    d = editor.diff("plan-a", 1, 2)
    assert d.reordered is False
    editor.close()


def test_diff_no_changes_between_identical_versions(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    a = PlanItem(title="A")
    editor.create("plan-a", [a])
    editor.update("plan-a", [a])
    d = editor.diff("plan-a", 1, 2)
    assert d.added == []
    assert d.removed == []
    assert d.changed == []
    assert d.reordered is False
    editor.close()


def test_diff_from_version_and_to_version_fields(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    editor.create("plan-a", [PlanItem(title="A")])
    editor.update("plan-a", [PlanItem(title="A2")])
    d = editor.diff("plan-a", 1, 2)
    assert d.plan_id == "plan-a"
    assert d.from_version == 1
    assert d.to_version == 2
    editor.close()


# ---------------------------------------------------------------------------
# In-memory / persistence
# ---------------------------------------------------------------------------


def test_memory_editor_isolated_between_instances() -> None:
    a = _mem()
    b = _mem()
    a.create("plan-a", [PlanItem(title="X")])
    assert a.list_plans() == ["plan-a"]
    assert b.list_plans() == []
    a.close()
    b.close()


def test_file_backed_editor_persists_across_reopen(tmp_path: Path) -> None:
    db = tmp_path / "plans.db"
    e1 = PlanEditor(db)
    e1.create("plan-x", [PlanItem(title="persist me")])
    e1.close()

    e2 = PlanEditor(db)
    latest = e2.get("plan-x")
    assert latest is not None
    assert latest.items[0].title == "persist me"
    e2.close()
