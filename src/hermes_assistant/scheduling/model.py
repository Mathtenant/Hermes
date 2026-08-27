"""Pydantic models for the scheduling subsystem (Phase 3.5, §27).

Keeps the data layer separate from derivation logic so tests and the CLI can
import models without pulling in workalendar / icalendar.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel


class ItemKind(str, Enum):
    """Semantic role of a scheduled item."""

    milestone = "milestone"  # quality gate / decision point
    deadline = "deadline"    # deliverable due date
    task = "task"            # work item


class Reminder(BaseModel):
    """Maps to a VALARM component in the ICS output.

    ``lead_days`` → ``TRIGGER:-P{n}D`` (the calendar app fires the alarm *n*
    calendar days before the event's start; working-day awareness lives in
    ``derive.py``, not here).
    """

    lead_days: int
    note: str | None = None


class ScheduledItem(BaseModel):
    """One calendar entry derived from a ``ProjectPlan`` item.

    ``uid`` is the stable identifier that lets a calendar app *update* an
    existing entry on re-import instead of creating a duplicate.
    Only non-confidential fields (title, dates, tag, note) are present.
    """

    uid: str                  # stable: "hermes-{project_id}-{item_id}@local"
    project_id: str
    project_label: str        # CATEGORIES tag for color-coding on import
    item_id: str
    title: str                # NON-confidential summary only
    kind: ItemKind
    start: date | None = None  # for ranged work items
    due: date                  # the date that matters
    all_day: bool = True
    depends_on: list[str] = []  # item_ids this item directly depends on
    reminders: list[Reminder] = []
    note: str | None = None    # short, NON-confidential
    sequence: int = 0          # bump on change → ICS SEQUENCE for clean re-import

    # --- Ablaufplan (Projektablaufplan_Detail import) ---------------------- #
    # A detailed flow plan carries more than a date: which phase a task belongs
    # to, who owns it, and how far along it is. All optional and defaulted, so
    # every schedule.json written before these existed still validates, and the
    # ICS exporter — which reads only title/dates/note — is unaffected.
    phase: str = ""            # display name of the containing phase
    owner: str | None = None   # role or name, NON-confidential
    status: Literal["offen", "laufend", "erledigt", "blockiert"] = "offen"
    progress_pct: int | None = None  # 0–100, only when the plan states it

    # --- Cross-source sweep (hermes.faelligkeiten/v1) ---------------------- #
    # When every dated obligation in the project is swept into one list,
    # regardless of altitude or which document it came from, two things have to
    # travel with each row or the list stops being usable: how big the thing is,
    # and where it was found. Without `level` a Go-Live and "check an invoice"
    # sit side by side with nothing to sort them; without `source_hint` there is
    # no way back to the document a date came from when two disagree.
    level: Literal["meilenstein", "arbeitspaket", "aufgabe"] = "arbeitspaket"
    source_hint: str = ""      # originating file name, never a path


class Schedule(BaseModel):
    """A fully derived, dated schedule for one project."""

    project_id: str
    generated_at: datetime
    items: list[ScheduledItem]
    negative_float: list[str] = []  # item_ids that cannot meet the deadline → warn
