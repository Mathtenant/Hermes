"""Pydantic models for the Task store (Phase 2.5, spec §30)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class NodeKind(str):
    """Node kind taxonomy (stored as plain string for Pydantic compat)."""

    milestone = "milestone"
    deliverable = "deliverable"
    task = "task"
    decision = "decision"
    pendenz = "pendenz"
    assumption = "assumption"


# Valid node kind literals — used for validation.
_NODE_KINDS = frozenset(
    {"milestone", "deliverable", "task", "decision", "pendenz", "assumption"}
)


class TaskUpdate(BaseModel):
    """One immutable audit entry for a field change on a Task."""

    timestamp: datetime
    field: str          # which field changed
    old_value: Any
    new_value: Any
    changed_by: str     # user or "system"


class Task(BaseModel):
    """A node in the WBS tree (spec §30).

    ``extra="allow"`` ensures subclass fields (e.g. Pendenz.source) survive
    the SQLite round-trip when the row is fetched as a plain Task.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    node_kind: Literal[
        "milestone", "deliverable", "task", "decision", "pendenz", "assumption"
    ] = "task"
    title: str
    description: str = ""
    owner: str | None = None
    status: Literal["open", "closed", "blocked"] = "open"
    wbs_number: str = ""            # computed: "1", "1.1", "1.2.3", etc.
    parent_id: str | None = None
    children_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updates: list[TaskUpdate] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
