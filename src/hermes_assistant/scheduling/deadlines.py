"""Cross-project deadline aggregation (§27, §28).

Collects all scheduled items across multiple projects into a single view:
upcoming deadlines, same-day collisions across projects, and overdue items.
This is the "juggling multiple project deadlines" capability (§4 cap. 6).

Pure Python and deterministic — no LLM, no I/O.
"""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel

from hermes_assistant.scheduling.model import Schedule, ScheduledItem


class DeadlineView(BaseModel):
    """Aggregated cross-project deadline picture."""

    within_days: int
    upcoming: list[ScheduledItem]     # sorted by due, across ALL projects
    collisions: list[tuple[str, str]]  # (uid_a, uid_b) pairs due same day, different projects
    overdue: list[ScheduledItem]       # due < today


def cross_project_view(
    schedules: list[Schedule],
    *,
    within_days: int = 14,
    today: date | None = None,
) -> DeadlineView:
    """Aggregate every project's schedule into one deadline view.

    Parameters
    ----------
    schedules:
        All loaded project schedules.
    within_days:
        Look-ahead window in calendar days (default: 14).
    today:
        Reference date for "now". Defaults to ``date.today()``. Overridable
        in tests for deterministic results.

    Returns
    -------
    DeadlineView
        ``upcoming``: items due within ``within_days`` calendar days, sorted
        by due date (soonest first).
        ``collisions``: pairs of UIDs where two items from *different* projects
        share the same due date — a scheduling conflict to surface to the user.
        ``overdue``: items whose ``due`` date is before ``today``.
    """
    ref = today if today is not None else date.today()
    cutoff = ref + timedelta(days=within_days)

    all_items = [item for sched in schedules for item in sched.items]

    upcoming = sorted(
        [it for it in all_items if ref <= it.due <= cutoff],
        key=lambda it: it.due,
    )
    overdue = sorted(
        [it for it in all_items if it.due < ref],
        key=lambda it: it.due,
    )

    # Detect same-day collisions across DIFFERENT projects.
    by_due: dict[date, list[ScheduledItem]] = {}
    for item in all_items:
        by_due.setdefault(item.due, []).append(item)

    collisions: list[tuple[str, str]] = []
    for items_on_day in by_due.values():
        # Only flag pairs from different projects.
        cross = [it for it in items_on_day]
        for i, a in enumerate(cross):
            for b in cross[i + 1 :]:
                if a.project_id != b.project_id:
                    collisions.append((a.uid, b.uid))

    return DeadlineView(
        within_days=within_days,
        upcoming=upcoming,
        collisions=collisions,
        overdue=overdue,
    )
