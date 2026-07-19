"""Pydantic models for AI-generated improvement suggestions."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pydantic import BaseModel, Field, field_validator


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Suggestion(BaseModel):
    """An AI-generated improvement suggestion for a HERMES deliverable."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    text: str
    confidence: float  # 0.0 (low confidence) to 1.0 (high confidence)
    applied: bool = False
    parent_job_id: str | None = None  # links to the review job that generated this
    created_at: str = Field(default_factory=_now)
    applied_at: str | None = None
    plan_id: str | None = None      # plan this was applied to
    plan_version: int | None = None  # version created when applied

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"confidence must be between 0.0 and 1.0, got {v}")
        return v
