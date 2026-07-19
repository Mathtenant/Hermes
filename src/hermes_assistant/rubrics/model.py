"""Pydantic models for rubrics (the *program* the critic executes).

A :class:`Rubric` is a flat, non-recursive bundle of :class:`Criterion` and
:class:`AntiPattern` rows loaded from YAML. Severity re-uses the shared
:class:`~hermes_assistant.hermes.model.Severity` enum so findings, flags and
rubric criteria all speak one vocabulary.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel

from hermes_assistant.hermes.model import Severity


class Dimension(str, Enum):
    """Quality dimensions a rubric criterion can belong to."""

    completeness = "completeness"
    correctness = "correctness"
    internal_consistency = "internal_consistency"
    clarity = "clarity"
    risk_coverage = "risk_coverage"


# Binary checks are length-neutral (no verbosity bias); graded checks allow a
# ``partial`` result for criteria that admit degrees of satisfaction.
CheckType = Literal["binary", "graded"]


class Criterion(BaseModel):
    """One atomic, independently-checkable rubric rule.

    The critic makes exactly one ``structured()`` call per criterion, so each
    must be answerable in isolation from a single reading of the deliverable.
    """

    id: str
    dimension: Dimension
    text: str
    check_type: CheckType = "binary"
    severity_if_failed: Severity
    evidence_required: bool = True


class AntiPattern(BaseModel):
    """A named failure mode with a failing and a passing example.

    Anti-patterns sharpen the critic's judgement by showing, concretely, what a
    violation looks like versus a clean result. They are advisory context for
    the per-criterion prompt, not separately scored.
    """

    id: str
    text: str
    example_fail: str
    example_pass: str
    severity: Severity


class Rubric(BaseModel):
    """A versioned quality standard: criteria + anti-patterns for one type."""

    rubric_id: str
    version: str
    deliverable_type: str
    description: str = ""
    criteria: list[Criterion]
    anti_patterns: list[AntiPattern] = []

    def dimensions(self) -> list[Dimension]:
        """Return the distinct dimensions covered, in declaration order."""
        seen: list[Dimension] = []
        for c in self.criteria:
            if c.dimension not in seen:
                seen.append(c.dimension)
        return seen
