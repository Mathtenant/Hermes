"""Unit tests for hermes_assistant.tui.models (no textual required)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from hermes_assistant.dashboard_html import (
    DashboardData,
    ProjectSummary,
    TimelineEntry,
    WBSNode,
    load_dashboard_data,
)
from hermes_assistant.jobqueue.jobs import JobStore
from hermes_assistant.tasks.model import Task
from hermes_assistant.tasks.store import TaskStore
from hermes_assistant.tui.models import (
    build_project_cards,
    project_phase_and_deadline,
    validate_safe_view,
    wbs_rollup,
)

_NOW = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_leaf(wbs: str, status: str = "open") -> WBSNode:
    return WBSNode(id=f"id-{wbs}", wbs_number=wbs, title=f"Node {wbs}", kind="task", status=status)


@pytest.fixture()
def task_store() -> TaskStore:
    store = TaskStore(":memory:")
    store.create(Task(id="", title="Root task", node_kind="task"))
    return store


@pytest.fixture()
def job_store() -> JobStore:
    return JobStore(":memory:")


@pytest.fixture()
def empty_data(task_store: TaskStore, job_store: JobStore, tmp_path: Path) -> DashboardData:
    return load_dashboard_data(None, task_store=task_store, job_store=job_store,
                               projects_root=tmp_path, now=_NOW)


@pytest.fixture()
def data_with_projects(task_store: TaskStore, job_store: JobStore, tmp_path: Path) -> DashboardData:
    """DashboardData with two project directories and schedule-derived timeline entries."""
    p1 = tmp_path / "proj-alpha"
    p1.mkdir()
    p2 = tmp_path / "proj-beta"
    p2.mkdir()
    return load_dashboard_data(None, task_store=task_store, job_store=job_store,
                               projects_root=tmp_path, now=_NOW)


# ---------------------------------------------------------------------------
# wbs_rollup
# ---------------------------------------------------------------------------

class TestWbsRollup:
    def test_leaf_open(self) -> None:
        node = _make_leaf("1.1", status="open")
        pct, total, closed = wbs_rollup(node)
        assert pct == 0.0
        assert total == 1
        assert closed == 0

    def test_leaf_closed(self) -> None:
        node = _make_leaf("1.2", status="closed")
        pct, total, closed = wbs_rollup(node)
        assert pct == 100.0
        assert total == 1
        assert closed == 1

    def test_leaf_blocked(self) -> None:
        node = _make_leaf("1.3", status="blocked")
        pct, total, closed = wbs_rollup(node)
        assert pct == 0.0
        assert total == 1
        assert closed == 0

    def test_branch_two_children_mixed(self) -> None:
        child_closed = _make_leaf("1.1", status="closed")
        child_open = _make_leaf("1.2", status="open")
        parent = WBSNode(
            id="id-1", wbs_number="1", title="Parent", kind="task",
            status="open", children=[child_closed, child_open],
        )
        pct, total, closed = wbs_rollup(parent)
        # pct = mean(100, 0) = 50; total = 2 + 1 = 3; closed = 1 + 0 (parent open) = 1
        assert pct == pytest.approx(50.0)
        assert total == 3
        assert closed == 1

    def test_branch_all_closed(self) -> None:
        children = [_make_leaf(f"1.{i}", status="closed") for i in range(1, 4)]
        parent = WBSNode(
            id="id-1", wbs_number="1", title="Parent", kind="task",
            status="closed", children=children,
        )
        pct, total, closed = wbs_rollup(parent)
        assert pct == pytest.approx(100.0)
        assert total == 4   # 3 children + parent
        assert closed == 4  # all closed

    def test_nested_rollup(self) -> None:
        """Three levels deep: root → phase → tasks."""
        leaf_a = _make_leaf("1.1.1", status="closed")
        leaf_b = _make_leaf("1.1.2", status="open")
        mid = WBSNode(
            id="id-1.1", wbs_number="1.1", title="Mid", kind="task",
            status="open", children=[leaf_a, leaf_b],
        )
        root = WBSNode(
            id="id-1", wbs_number="1", title="Root", kind="task",
            status="open", children=[mid],
        )
        pct, total, closed = wbs_rollup(root)
        # mid pct = mean(100, 0) = 50; root pct = mean(50) = 50
        assert pct == pytest.approx(50.0)
        assert total == 4
        assert closed == 1  # only leaf_a

    def test_no_children_branch_empty(self) -> None:
        node = WBSNode(
            id="id-empty", wbs_number="2", title="Empty branch", kind="task",
            status="open", children=[],
        )
        pct, total, closed = wbs_rollup(node)
        assert pct == 0.0
        assert total == 1
        assert closed == 0


# ---------------------------------------------------------------------------
# project_phase_and_deadline
# ---------------------------------------------------------------------------

class TestProjectPhaseAndDeadline:
    def test_missing_project_returns_dash(self, empty_data: DashboardData) -> None:
        phase, deadline = project_phase_and_deadline("nonexistent", empty_data)
        assert phase == "—"
        assert deadline is None

    def test_project_without_timeline(self, data_with_projects: DashboardData) -> None:
        # proj-alpha exists as a directory, no schedule.json → no timeline entries
        phase, deadline = project_phase_and_deadline("proj-alpha", data_with_projects)
        # phase is the label or project_id; deadline is None because no timeline
        assert phase in ("proj-alpha", "—", "")
        assert deadline is None

    def test_project_with_timeline_entries(self, tmp_path: Path) -> None:
        """Inject timeline entries manually via model_construct."""
        entries = [
            TimelineEntry(date="2026-08-01", label="M1", kind="milestone",
                          status="future", project_id="proj-alpha"),
            TimelineEntry(date="2026-09-15", label="D1", kind="deadline",
                          status="future", project_id="proj-alpha"),
        ]
        data = DashboardData(
            generated_at="2026-07-16T09:00:00Z",
            projects=[ProjectSummary(project_id="proj-alpha", label="Alpha Project")],
            timeline=entries,
        )
        phase, deadline = project_phase_and_deadline("proj-alpha", data)
        assert phase == "Alpha Project"
        assert deadline == date(2026, 9, 15)

    def test_deadline_max_of_multiple_dates(self) -> None:
        entries = [
            TimelineEntry(date="2026-08-01", label="T1", kind="task",
                          status="future", project_id="p1"),
            TimelineEntry(date="2026-12-31", label="T2", kind="deadline",
                          status="future", project_id="p1"),
            TimelineEntry(date="2026-07-20", label="T3", kind="milestone",
                          status="future", project_id="p1"),
        ]
        data = DashboardData(
            generated_at="2026-07-16T09:00:00Z",
            projects=[ProjectSummary(project_id="p1", label="P1")],
            timeline=entries,
        )
        _, deadline = project_phase_and_deadline("p1", data)
        assert deadline == date(2026, 12, 31)


# ---------------------------------------------------------------------------
# validate_safe_view
# ---------------------------------------------------------------------------

class TestValidateSafeView:
    def test_clean_data_no_violations(self, empty_data: DashboardData) -> None:
        violations = validate_safe_view(empty_data)
        assert violations == []

    def test_clean_data_with_projects(self, data_with_projects: DashboardData) -> None:
        violations = validate_safe_view(data_with_projects)
        assert violations == []

    def test_detects_forbidden_field_name_in_json(self, empty_data: DashboardData) -> None:
        """Patch DashboardData.model_dump_json at the class level to inject a forbidden key."""
        poisoned = '{"raw_notes": "secret content", "generated_at": "2026-07-16"}'
        with patch.object(DashboardData, "model_dump_json", return_value=poisoned):
            violations = validate_safe_view(empty_data)
        assert any("raw_notes" in v for v in violations)

    def test_detects_confidential_keyword(self, empty_data: DashboardData) -> None:
        """The word 'rationale' as a JSON key triggers the confidential keyword check."""
        poisoned = '{"rationale": "internal reasoning", "generated_at": "2026-07-16"}'
        with patch.object(DashboardData, "model_dump_json", return_value=poisoned):
            violations = validate_safe_view(empty_data)
        # "rationale" is both a forbidden field and a confidential keyword
        assert len(violations) >= 1

    def test_detects_filesystem_path(self, empty_data: DashboardData) -> None:
        poisoned = '{"label": "/Users/lt/secret/file.txt", "generated_at": "2026-07-16"}'
        with patch.object(DashboardData, "model_dump_json", return_value=poisoned):
            violations = validate_safe_view(empty_data)
        assert any("filesystem path" in v for v in violations)

    def test_no_false_positive_on_normal_text(self) -> None:
        data = DashboardData(
            generated_at="2026-07-16T09:00:00Z",
            projects=[ProjectSummary(project_id="delta-review", label="Delta Review")],
        )
        violations = validate_safe_view(data)
        assert violations == []


# ---------------------------------------------------------------------------
# build_project_cards
# ---------------------------------------------------------------------------

class TestBuildProjectCards:
    def test_returns_one_card_per_project(self, data_with_projects: DashboardData) -> None:
        cards = build_project_cards(data_with_projects)
        assert len(cards) == len(data_with_projects.projects)

    def test_card_fields_populated(self) -> None:
        data = DashboardData(
            generated_at="2026-07-16T09:00:00Z",
            projects=[ProjectSummary(project_id="myproj", label="My Project")],
            timeline=[
                TimelineEntry(date="2026-09-01", label="M1", kind="milestone",
                              status="future", project_id="myproj")
            ],
        )
        cards = build_project_cards(data)
        assert len(cards) == 1
        card = cards[0]
        assert card.project_id == "myproj"
        assert card.label == "My Project"
        assert card.deadline == date(2026, 9, 1)
        assert card.n_timeline == 1
        assert isinstance(card.pct_done, float)
        assert 0.0 <= card.pct_done <= 100.0

    def test_empty_data_no_cards(self, empty_data: DashboardData) -> None:
        cards = build_project_cards(empty_data)
        # empty_data has no projects directory entries → 0 cards
        assert cards == []
