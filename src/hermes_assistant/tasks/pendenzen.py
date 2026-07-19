"""Pendenz model — Phase 2.6 (spec §31).

A Pendenz is a Task specialised for action items that arise during reviews,
decisions, meetings, or manual capture.  It extends ``Task`` with provenance
fields (source, raised_by, due_date, priority).
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal

from hermes_assistant.tasks.model import Task


class PendenzSource(str, Enum):
    """Origin of a pendenz."""

    manual = "manual"
    review = "review"
    decision = "decision"
    meeting = "meeting"
    facilitator_import = "facilitator_import"


class Pendenz(Task):
    """An action-item node in the task tree (node_kind = "pendenz")."""

    node_kind: Literal["pendenz"] = "pendenz"
    source: PendenzSource = PendenzSource.manual
    source_ref: str | None = None   # id of the review/decision/meeting that raised it
    raised_by: str | None = None
    raised_at: datetime | None = None
    due_date: date | None = None
    priority: Literal["low", "medium", "high", "blocker"] = "medium"
