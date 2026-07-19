"""Deterministic dependency-aware scheduler for HERMES project plans (§26).

Pure Python, no LLM. All date arithmetic uses the Zürich working calendar
(``workalendar.europe.Zurich``) to skip weekends and public holidays.

Algorithm
---------
1. Extract all milestones (and optionally outcomes) from the ``ProjectPlan``.
2. Build a dependency graph from each item's ``depends_on`` list.
3. Topological sort (Kahn's algorithm) — raises ``CyclicDependencyError`` on
   cycles, as a cycle implies a plan that cannot be scheduled.
4. Forward pass from ``start_date``: each item's ``due`` is
   ``effort_days`` working days after the latest predecessor's ``due`` date.
   If an item has no predecessors, it starts on ``start_date``.
5. Negative-float detection: any item whose computed ``due`` exceeds the hard
   ``deadline`` is listed in ``Schedule.negative_float`` and surfaced to the
   user — exactly the kind of foresight a senior PM surfaces early.
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, date, datetime
from typing import Protocol

from hermes_assistant.hermes.model import ProjectPlan
from hermes_assistant.scheduling.model import (
    ItemKind,
    Reminder,
    Schedule,
    ScheduledItem,
)

# Default effort/duration if a milestone carries no effort_days hint.
_DEFAULT_EFFORT_DAYS: float = 1.0

# Default reminder lead times (calendar days) per item kind.
_DEFAULT_REMINDER_MILESTONE = 5
_DEFAULT_REMINDER_TASK = 2


class CyclicDependencyError(ValueError):
    """Raised when the dependency graph contains a cycle."""


class _Calendar(Protocol):
    """Minimal interface we use from workalendar (duck-typed for testability)."""

    def is_working_day(self, day: date) -> bool: ...
    def add_working_days(self, day: date, n: int) -> date: ...


def _zurich_calendar() -> _Calendar:
    from typing import cast

    from workalendar.europe import Zurich
    return cast(_Calendar, Zurich())


def _next_working_day(d: date, cal: _Calendar) -> date:
    """Return ``d`` if it is a working day, else the next one."""
    if cal.is_working_day(d):
        return d
    return cal.add_working_days(d, 1)


def _add_working_days(d: date, n: float, cal: _Calendar) -> date:
    """Advance ``d`` by ``n`` working days (rounded to nearest integer)."""
    return cal.add_working_days(d, max(1, round(n)))


# ---------------------------------------------------------------------------
# Internal item representation (flattened from plan structure)
# ---------------------------------------------------------------------------

class _Item:
    """Flat scheduling unit derived from a ``Milestone``."""

    __slots__ = ("id", "title", "kind", "effort_days", "depends_on")

    def __init__(
        self,
        id: str,
        title: str,
        kind: ItemKind,
        effort_days: float,
        depends_on: list[str],
    ) -> None:
        self.id = id
        self.title = title
        self.kind = kind
        self.effort_days = effort_days
        self.depends_on = depends_on


def _extract_items(plan: ProjectPlan) -> list[_Item]:
    """Flatten a ``ProjectPlan`` into a list of scheduling items.

    We schedule all milestones. Outcomes that carry an ``effort_days`` hint
    are also included as tasks so their effort contributes to the timeline.
    """
    items: list[_Item] = []
    seen: set[str] = set()

    for phase in plan.phases:
        for ms in phase.milestones:
            if ms.id not in seen:
                items.append(
                    _Item(
                        id=ms.id,
                        title=ms.name,
                        kind=ItemKind.milestone,
                        effort_days=ms.effort_days or _DEFAULT_EFFORT_DAYS,
                        depends_on=list(ms.depends_on),
                    )
                )
                seen.add(ms.id)
        for oc in phase.outcomes:
            if oc.effort_days is not None and oc.id not in seen:
                items.append(
                    _Item(
                        id=oc.id,
                        title=oc.name,
                        kind=ItemKind.task,
                        effort_days=oc.effort_days,
                        depends_on=list(oc.depends_on),
                    )
                )
                seen.add(oc.id)

    return items


def topological_sort(items: list[_Item]) -> list[_Item]:
    """Kahn's algorithm — returns a valid ordering or raises ``CyclicDependencyError``."""
    ids = {it.id for it in items}
    index: dict[str, _Item] = {it.id: it for it in items}

    # in-degree count; ignore depends_on references to ids outside this set
    in_deg: dict[str, int] = {it.id: 0 for it in items}
    adj: dict[str, list[str]] = {it.id: [] for it in items}
    for it in items:
        for dep in it.depends_on:
            if dep in ids:
                in_deg[it.id] += 1
                adj[dep].append(it.id)

    queue: deque[str] = deque(nid for nid, d in in_deg.items() if d == 0)
    ordered: list[_Item] = []

    while queue:
        nid = queue.popleft()
        ordered.append(index[nid])
        for child in adj[nid]:
            in_deg[child] -= 1
            if in_deg[child] == 0:
                queue.append(child)

    if len(ordered) != len(items):
        cycle_members = [it.id for it in items if it.id not in {o.id for o in ordered}]
        raise CyclicDependencyError(
            f"Dependency cycle detected among: {cycle_members}"
        )

    return ordered


def derive_schedule(
    plan: ProjectPlan,
    *,
    project_id: str,
    project_label: str,
    start_date: date,
    deadline: date | None = None,
    reminder_days_milestone: int = _DEFAULT_REMINDER_MILESTONE,
    reminder_days_task: int = _DEFAULT_REMINDER_TASK,
    use_zurich_holidays: bool = True,
    calendar: _Calendar | None = None,
    sequence: int = 0,
) -> Schedule:
    """Derive a fully-dated ``Schedule`` from a ``ProjectPlan``.

    Parameters
    ----------
    plan:
        The project plan whose milestones / outcomes are scheduled.
    project_id:
        Stable project identifier (used in ICS UIDs).
    project_label:
        Human-readable label for CATEGORIES tagging in ICS output.
    start_date:
        Earliest date work can begin (forward pass anchor).
    deadline:
        Hard end date. Items computed past this date appear in
        ``Schedule.negative_float`` and are surfaced as warnings.
    reminder_days_milestone:
        Default reminder lead time (calendar days) for milestone events.
    reminder_days_task:
        Default reminder lead time (calendar days) for task events.
    use_zurich_holidays:
        If ``True`` (default) the Zürich public-holiday calendar is used.
        Pass ``calendar=...`` to supply a custom or mock calendar instead.
    calendar:
        Override the working-day calendar (useful in tests).
    sequence:
        ICS SEQUENCE value for all items in this schedule (bump on rebuild).
    """
    cal: _Calendar = calendar if calendar is not None else (
        _zurich_calendar() if use_zurich_holidays else _SimpleWeekdayCal()
    )

    raw_items = _extract_items(plan)
    if not raw_items:
        return Schedule(
            project_id=project_id,
            generated_at=datetime.now(tz=UTC),
            items=[],
            negative_float=[],
        )

    ordered = topological_sort(raw_items)

    # Forward pass: track latest due date per item id so dependents can look it up.
    anchor = _next_working_day(start_date, cal)
    due_by_id: dict[str, date] = {}

    scheduled: list[ScheduledItem] = []
    negative_float: list[str] = []

    for item in ordered:
        # earliest we can start this item = day AFTER the latest dependency's due
        dep_dates = [due_by_id[dep] for dep in item.depends_on if dep in due_by_id]
        if dep_dates:
            earliest_start = cal.add_working_days(max(dep_dates), 1)
        else:
            earliest_start = anchor

        item_due = _add_working_days(earliest_start, item.effort_days, cal)
        due_by_id[item.id] = item_due

        # Negative float: item due is later than the hard deadline.
        if deadline is not None and item_due > deadline:
            negative_float.append(item.id)

        lead = (
            reminder_days_milestone
            if item.kind == ItemKind.milestone
            else reminder_days_task
        )
        reminders = [Reminder(lead_days=lead)]

        uid = f"hermes-{project_id}-{item.id}@local"
        scheduled.append(
            ScheduledItem(
                uid=uid,
                project_id=project_id,
                project_label=project_label,
                item_id=item.id,
                title=item.title,
                kind=item.kind,
                start=earliest_start,
                due=item_due,
                all_day=True,
                depends_on=item.depends_on,
                reminders=reminders,
                sequence=sequence,
            )
        )

    return Schedule(
        project_id=project_id,
        generated_at=datetime.now(tz=UTC),
        items=scheduled,
        negative_float=negative_float,
    )


class _SimpleWeekdayCal:
    """Minimal working-day calendar: skip Saturday/Sunday only, no holidays.

    Used when ``use_zurich_holidays=False`` and no custom calendar is provided.
    """

    def is_working_day(self, day: date) -> bool:
        return day.weekday() < 5  # Mon=0 … Fri=4

    def add_working_days(self, day: date, n: int) -> date:
        from datetime import timedelta
        current = day
        remaining = max(n, 0)
        while remaining > 0:
            current += timedelta(days=1)
            if self.is_working_day(current):
                remaining -= 1
        return current
