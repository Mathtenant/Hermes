"""Pydantic models for the HERMES plan editor."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(UTC).isoformat()


class PlanItemStatus(str, Enum):
    """Progress state of a single plan item."""

    open = "open"
    in_progress = "in_progress"
    done = "done"
    blocked = "blocked"


class PlanItem(BaseModel):
    """One work item (task, deliverable, or milestone) within a plan."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    title: str
    phase: str = ""
    assignee: str = ""
    role: str = ""
    status: PlanItemStatus = PlanItemStatus.open
    order: int = 0  # position in the plan (for drag-and-drop reordering)


class PlanVersion(BaseModel):
    """An immutable snapshot of a plan at a given version number."""

    plan_id: str
    version: int
    items: list[PlanItem]
    author: str = ""
    created_at: str = Field(default_factory=_now)


class PlanDiff(BaseModel):
    """Difference between two plan versions."""

    plan_id: str
    from_version: int
    to_version: int
    added: list[PlanItem] = []
    removed: list[PlanItem] = []
    changed: list[tuple[PlanItem, PlanItem]] = []  # (old, new)
    reordered: bool = False
