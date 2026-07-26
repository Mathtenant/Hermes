"""Performance tests: Plan Editor at scale.

Validates that reordering, diff generation, and version history access stay
well within acceptable latency even with large plans and long histories.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from hermes_assistant.plans.editor import PlanEditor
from hermes_assistant.plans.model import PlanItem


@pytest.fixture()
def editor(tmp_path: Path) -> PlanEditor:
    return PlanEditor(tmp_path / "plans_perf.db")


def _make_items(n: int) -> list[PlanItem]:
    return [PlanItem(title=f"Task {i}", phase=f"Phase {i // 10 + 1}") for i in range(n)]


def test_plan_reorder_20_phases_50_outcomes_under_200ms(editor: PlanEditor) -> None:
    """Reordering a plan with 1000 items (20 × 50) finishes in under 200 ms."""
    items = _make_items(1000)
    editor.create("big-plan", items)
    item_ids = [i.id for i in reversed(items)]  # full reversal
    start = time.perf_counter()
    v2 = editor.reorder("big-plan", item_ids)
    elapsed = (time.perf_counter() - start) * 1000
    assert v2.version == 2
    assert elapsed < 200, f"reorder(1000 items) took {elapsed:.1f} ms (limit 200 ms)"


def test_plan_diff_generation_under_100ms(editor: PlanEditor) -> None:
    """Diff generation between two large versions finishes in under 100 ms."""
    items_v1 = _make_items(500)
    editor.create("diff-plan", items_v1)
    items_v2 = items_v1[:400] + _make_items(20)  # remove 100, add 20 new
    editor.update("diff-plan", items_v2)
    start = time.perf_counter()
    diff = editor.diff("diff-plan", 1, 2)
    elapsed = (time.perf_counter() - start) * 1000
    assert len(diff.removed) == 100
    assert len(diff.added) == 20
    assert elapsed < 100, f"diff(500 items) took {elapsed:.1f} ms (limit 100 ms)"


def test_plan_100_version_history_scroll_under_500ms(editor: PlanEditor) -> None:
    """list_versions() on a plan with 100 versions completes in under 500 ms."""
    items = _make_items(10)
    editor.create("history-plan", items)
    for _ in range(99):
        editor.update("history-plan", items)
    start = time.perf_counter()
    versions = editor.list_versions("history-plan")
    elapsed = (time.perf_counter() - start) * 1000
    assert len(versions) == 100
    assert elapsed < 500, f"list_versions(100 versions) took {elapsed:.1f} ms (limit 500 ms)"
