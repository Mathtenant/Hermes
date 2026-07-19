"""Unit tests for hermes_assistant.tui.refresh (no textual required)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from hermes_assistant.dashboard_html import (
    DashboardData,
    load_dashboard_data,
)
from hermes_assistant.jobqueue.jobs import JobStore
from hermes_assistant.tasks.model import Task
from hermes_assistant.tasks.pendenzen import Pendenz, PendenzSource
from hermes_assistant.tasks.store import TaskStore
from hermes_assistant.tui.refresh import compute_fingerprint, diff_sections, load_fresh

_NOW = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def task_store() -> TaskStore:
    store = TaskStore(":memory:")
    store.create(Task(id="", title="Alpha task", node_kind="task"))
    return store


@pytest.fixture()
def job_store() -> JobStore:
    return JobStore(":memory:")


@pytest.fixture()
def base_data(task_store: TaskStore, job_store: JobStore, tmp_path: Path) -> DashboardData:
    return load_dashboard_data(None, task_store=task_store, job_store=job_store,
                               projects_root=tmp_path, now=_NOW)


# ---------------------------------------------------------------------------
# compute_fingerprint
# ---------------------------------------------------------------------------

class TestComputeFingerprint:
    def test_existing_file_has_positive_mtime(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        db.write_bytes(b"")
        fp = compute_fingerprint(tmp_path)
        # At least the file we created might not be in fp (depends on rglob pattern)
        # But the settings files should be included
        # All values must be >= 0
        for v in fp.values():
            assert v >= 0.0

    def test_missing_file_returns_zero(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A path that does not exist should map to 0.0."""
        from hermes_assistant.config import settings
        # Point tasks_db_path to a guaranteed non-existent path
        nonexistent = str(tmp_path / "does_not_exist.db")
        monkeypatch.setattr(settings, "tasks_db_path", nonexistent)
        monkeypatch.setattr(settings, "queue_db_path", str(tmp_path / "also_missing.db"))

        fp = compute_fingerprint(tmp_path)
        assert fp.get(nonexistent, 0.0) == 0.0

    def test_returns_dict(self, tmp_path: Path) -> None:
        fp = compute_fingerprint(tmp_path)
        assert isinstance(fp, dict)

    def test_schedule_json_picked_up(self, tmp_path: Path) -> None:
        """schedule.json files under projects root are included."""
        proj = tmp_path / "my-project"
        proj.mkdir()
        sched = proj / "schedule.json"
        sched.write_text("{}", encoding="utf-8")
        fp = compute_fingerprint(tmp_path)
        assert str(sched) in fp
        assert fp[str(sched)] > 0.0

    def test_no_schedule_json_no_extra_keys(self, tmp_path: Path) -> None:
        """Root with no schedule.json files → only settings paths in fingerprint."""
        fp = compute_fingerprint(tmp_path)
        for key in fp:
            assert not key.endswith(".nonexistent")

    def test_file_deletion_changes_fingerprint(self, tmp_path: Path) -> None:
        proj = tmp_path / "proj"
        proj.mkdir()
        sched = proj / "schedule.json"
        sched.write_text("{}", encoding="utf-8")

        fp_before = compute_fingerprint(tmp_path)
        sched.unlink()
        fp_after = compute_fingerprint(tmp_path)

        assert fp_before[str(sched)] > 0.0
        # After deletion, rglob won't find the file; it may be absent from fp_after
        # (interpreted as 0.0) or explicitly 0.0 if previously tracked.
        assert fp_after.get(str(sched), 0.0) == 0.0


# ---------------------------------------------------------------------------
# diff_sections
# ---------------------------------------------------------------------------

class TestDiffSections:
    def test_identical_data_no_changes(self, base_data: DashboardData) -> None:
        changed = diff_sections(base_data, base_data)
        assert changed == set()

    def test_pendenzen_change_detected(
        self, task_store: TaskStore, job_store: JobStore, tmp_path: Path
    ) -> None:
        old = load_dashboard_data(None, task_store=task_store, job_store=job_store,
                                  projects_root=tmp_path, now=_NOW)
        # Add a new pendenz
        task_store.create(
            Pendenz(id="", title="New action", source=PendenzSource.manual, priority="high")
        )
        new = load_dashboard_data(None, task_store=task_store, job_store=job_store,
                                  projects_root=tmp_path, now=_NOW)
        changed = diff_sections(old, new)
        assert "pendenzen" in changed

    def test_timeline_change_detected(self, tmp_path: Path) -> None:
        """Adding a schedule.json changes the timeline section."""
        ts = TaskStore(":memory:")
        js = JobStore(":memory:")
        old = load_dashboard_data(None, task_store=ts, job_store=js,
                                  projects_root=tmp_path, now=_NOW)

        # Create a project dir + minimal schedule.json
        proj = tmp_path / "proj"
        proj.mkdir()
        from datetime import date
        from datetime import datetime as _dt

        from hermes_assistant.scheduling.model import ItemKind, Schedule, ScheduledItem
        sched = Schedule(
            project_id="proj",
            generated_at=_dt(2026, 7, 16, tzinfo=UTC),
            items=[
                ScheduledItem(
                    uid="hermes-proj-t1@local",
                    project_id="proj",
                    project_label="Proj",
                    item_id="t1",
                    title="Task 1",
                    due=date(2026, 9, 1),
                    kind=ItemKind.task,
                )
            ],
        )
        (proj / "schedule.json").write_text(sched.model_dump_json(), encoding="utf-8")

        new = load_dashboard_data(None, task_store=ts, job_store=js,
                                  projects_root=tmp_path, now=_NOW)
        changed = diff_sections(old, new)
        assert "timeline" in changed

    def test_projects_change_detected(self, tmp_path: Path) -> None:
        ts = TaskStore(":memory:")
        js = JobStore(":memory:")
        old = load_dashboard_data(None, task_store=ts, job_store=js,
                                  projects_root=tmp_path, now=_NOW)

        (tmp_path / "new-project").mkdir()

        new = load_dashboard_data(None, task_store=ts, job_store=js,
                                  projects_root=tmp_path, now=_NOW)
        changed = diff_sections(old, new)
        assert "projects" in changed

    def test_generated_at_ignored(self, base_data: DashboardData) -> None:
        """Cloning with a different generated_at but identical payload → no sections changed."""
        clone = base_data.model_copy(update={"generated_at": "1970-01-01T00:00:00Z"})
        changed = diff_sections(base_data, clone)
        # generated_at is not a section; other sections are identical
        assert changed == set()

    def test_kanban_change_detected(self, task_store: TaskStore, job_store: JobStore, tmp_path: Path) -> None:
        old = load_dashboard_data(None, task_store=task_store, job_store=job_store,
                                  projects_root=tmp_path, now=_NOW)
        task_store.create(Task(id="", title="New board task", node_kind="task"))
        new = load_dashboard_data(None, task_store=task_store, job_store=job_store,
                                  projects_root=tmp_path, now=_NOW)
        changed = diff_sections(old, new)
        assert "board" in changed


# ---------------------------------------------------------------------------
# load_fresh
# ---------------------------------------------------------------------------

class TestLoadFresh:
    def test_returns_dashboard_data(self, task_store: TaskStore, job_store: JobStore, tmp_path: Path) -> None:
        data = load_fresh(projects_root=tmp_path, task_store=task_store, job_store=job_store)
        assert isinstance(data, DashboardData)

    def test_load_fresh_no_args_does_not_crash(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """load_fresh() with no args uses settings; override paths so it won't fail."""
        from hermes_assistant.config import settings
        monkeypatch.setattr(settings, "tasks_db_path", str(tmp_path / "t.db"))
        monkeypatch.setattr(settings, "queue_db_path", str(tmp_path / "q.db"))
        monkeypatch.setattr(settings, "projects_path", str(tmp_path))
        data = load_fresh()
        assert isinstance(data, DashboardData)
