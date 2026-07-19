"""Refresh worker and fingerprinting (zero textual imports — unit-testable)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from hermes_assistant.dashboard_html import DashboardData, load_dashboard_data


class RefreshResult(BaseModel):
    """Container returned by the background data loader."""

    model_config = {"arbitrary_types_allowed": True}

    data: DashboardData
    changed_sections: set[str]  # {"timeline", "board", "pendenzen", "reviews", "projects"}
    fingerprint: dict[str, float]


def compute_fingerprint(projects_root: Path | None = None) -> dict[str, float]:
    """Stat all tracked data files; return {absolute_path_str: mtime}.

    Missing files map to 0.0 so callers can detect file creation.
    """
    from hermes_assistant.config import settings

    root = projects_root or Path(settings.projects_path)
    fp: dict[str, float] = {}

    candidate_files: list[Path] = [
        Path(settings.tasks_db_path),
        Path(settings.queue_db_path),
    ]
    if root.exists():
        candidate_files.extend(root.rglob("schedule.json"))

    for f in candidate_files:
        try:
            fp[str(f)] = f.stat().st_mtime if f.exists() else 0.0
        except OSError:
            fp[str(f)] = 0.0

    return fp


def diff_sections(old: DashboardData, new: DashboardData) -> set[str]:
    """Compare two DashboardData snapshots; return names of changed sections.

    Excludes ``generated_at`` so a clock-only change is not reported as a diff.
    """
    changed: set[str] = set()
    if old.projects != new.projects:
        changed.add("projects")
    if old.timeline != new.timeline:
        changed.add("timeline")
    if old.kanban != new.kanban:
        changed.add("board")
    if old.pendenzen != new.pendenzen:
        changed.add("pendenzen")
    if old.reviews != new.reviews:
        changed.add("reviews")
    return changed


def load_fresh(
    projects_root: Path | None = None,
    task_store: object | None = None,
    job_store: object | None = None,
    now: datetime | None = None,
) -> DashboardData:
    """Load a fresh DashboardData snapshot.

    Accepts optional store overrides for testing; production code calls with
    no arguments (stores are opened from settings inside load_dashboard_data).

    Args:
        now: Override the current timestamp for virtual-clock testing.
             When None (default) the real UTC time is used.
    """
    kwargs: dict[str, object] = {}
    if task_store is not None:
        kwargs["task_store"] = task_store
    if job_store is not None:
        kwargs["job_store"] = job_store
    if projects_root is not None:
        kwargs["projects_root"] = projects_root
    if now is not None:
        kwargs["now"] = now
    return load_dashboard_data(None, **kwargs)  # type: ignore[arg-type]
