"""Pydantic models for project risk management."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(UTC).isoformat()


class RiskSeverity(str, Enum):
    """Risk impact severity."""

    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class RiskStatus(str, Enum):
    """Lifecycle state of a tracked risk."""

    open = "open"
    mitigated = "mitigated"
    accepted = "accepted"
    closed = "closed"


class Risk(BaseModel):
    """A single tracked project risk."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    title: str
    description: str = ""
    severity: RiskSeverity = RiskSeverity.medium
    likelihood: int = 3  # 1 (very unlikely) – 5 (almost certain)
    owner: str = ""
    status: RiskStatus = RiskStatus.open
    confidential: bool = False
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    accepted_at: str | None = None

    # Derived read-only helpers
    @property
    def risk_score(self) -> int:
        """Numeric product of severity × likelihood (used for sorting)."""
        _sev_weight = {
            RiskSeverity.low: 1,
            RiskSeverity.medium: 2,
            RiskSeverity.high: 3,
            RiskSeverity.critical: 4,
        }
        return _sev_weight[self.severity] * self.likelihood
