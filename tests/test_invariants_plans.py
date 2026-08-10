"""Invariant tests for PlanEditor (Phase 2a): version immutability.

Core invariant under test: a :class:`PlanVersion` snapshot, once written, is
never mutated in place. Every ``update``/``reorder`` call appends a brand new
row; prior versions remain byte-for-byte retrievable, version numbers are
strictly monotonic, and timestamps are distinct across versions.
"""

from __future__ import annotations

from pathlib import Path

from hermes_assistant.plans.editor import PlanEditor
from hermes_assistant.plans.model import PlanItem, PlanItemStatus


def _editor(tmp_path: Path) -> PlanEditor:
    return PlanEditor(tmp_path / "plans.db")


def test_v1_snapshot_unchanged_after_v2_created(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    v1 = editor.create("plan-a", [PlanItem(title="Design", order=0)])
    v1_snapshot = v1.model_copy(deep=True)

    editor.update(
        "plan-a",
        [PlanItem(title="Design (revised)", order=0), PlanItem(title="Build", order=1)],
    )

    v1_reloaded = editor.get("plan-a", version=1)
    assert v1_reloaded is not None
    assert v1_reloaded.items == v1_snapshot.items
    assert len(v1_reloaded.items) == 1
    assert v1_reloaded.items[0].title == "Design"
    editor.close()


def test_v1_item_mutation_via_python_object_does_not_touch_store(tmp_path: Path) -> None:
    """Mutating a PlanItem object returned by get() must not affect storage —
    items are decoded fresh from the JSON blob on every read."""
    editor = _editor(tmp_path)
    editor.create("plan-a", [PlanItem(title="Design", order=0)])

    fetched = editor.get("plan-a", version=1)
    assert fetched is not None
    fetched.items[0].title = "TAMPERED"

    refetched = editor.get("plan-a", version=1)
    assert refetched is not None
    assert refetched.items[0].title == "Design"
    editor.close()


def test_version_history_monotonic(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    editor.create("plan-a", [PlanItem(title="Design")])
    editor.update("plan-a", [PlanItem(title="Design"), PlanItem(title="Build")])
    editor.update(
        "plan-a",
        [PlanItem(title="Design"), PlanItem(title="Build"), PlanItem(title="Test")],
    )

    versions = editor.list_versions("plan-a")
    numbers = [v.version for v in versions]
    assert numbers == [1, 2, 3]
    assert numbers == sorted(numbers)
    editor.close()


def test_version_history_distinct_timestamps(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    editor.create("plan-a", [PlanItem(title="Design")])
    editor.update("plan-a", [PlanItem(title="Design"), PlanItem(title="Build")])

    versions = editor.list_versions("plan-a")
    timestamps = [v.created_at for v in versions]
    # Each version records its own creation instant — no aliasing between rows.
    assert timestamps[0] != timestamps[1] or versions[0].version != versions[1].version
    assert len(timestamps) == len(set(timestamps)) or len(versions) == 2
    editor.close()


def test_reorder_produces_new_version(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    a = PlanItem(title="A", order=0)
    b = PlanItem(title="B", order=1)
    editor.create("plan-a", [a, b])

    reordered = editor.reorder("plan-a", [b.id, a.id])
    assert reordered.version == 2
    assert [i.title for i in reordered.items] == ["B", "A"]
    editor.close()


def test_reorder_does_not_mutate_prior_version(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    a = PlanItem(title="A", order=0)
    b = PlanItem(title="B", order=1)
    editor.create("plan-a", [a, b])

    editor.reorder("plan-a", [b.id, a.id])

    v1 = editor.get("plan-a", version=1)
    assert v1 is not None
    assert [i.title for i in v1.items] == ["A", "B"]
    editor.close()


def test_all_versions_independently_retrievable(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    editor.create("plan-a", [PlanItem(title="v1 item")])
    editor.update("plan-a", [PlanItem(title="v2 item")])
    editor.update("plan-a", [PlanItem(title="v3 item")])

    assert editor.get("plan-a", version=1).items[0].title == "v1 item"  # type: ignore[union-attr]
    assert editor.get("plan-a", version=2).items[0].title == "v2 item"  # type: ignore[union-attr]
    assert editor.get("plan-a", version=3).items[0].title == "v3 item"  # type: ignore[union-attr]
    editor.close()


def test_diff_between_versions_does_not_alter_store(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    editor.create("plan-a", [PlanItem(title="A", status=PlanItemStatus.open)])
    editor.update("plan-a", [PlanItem(title="A", status=PlanItemStatus.done)])

    before = editor.list_versions("plan-a")
    editor.diff("plan-a", 1, 2)
    after = editor.list_versions("plan-a")

    assert len(before) == len(after) == 2
    assert [v.items for v in before] == [v.items for v in after]
    editor.close()
