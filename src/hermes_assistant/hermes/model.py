"""Pydantic models for HERMES 2022 structures."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel


class Approach(str, Enum):
    """Solution creation approach."""

    traditional = "traditional"
    agile = "agile"
    hybrid = "hybrid"


class Outcome(BaseModel):
    """Deliverable or state outcome."""

    id: str
    name: str
    kind: str  # "document" | "state" | "decision"
    mandatory: bool  # the "X" minimum docs
    module: str
    phase: str = ""  # id of the phase this outcome belongs to
    # Name of the sizing flag that gates this outcome. ``None`` = always
    # required; otherwise the outcome is mandatory only when the flag is set.
    condition: str | None = None
    # Scheduling (Phase 3.5): optional dependency and effort hints.
    # Defaults preserve existing plan JSON validity (non-breaking).
    depends_on: list[str] = []   # ids of outcomes/milestones this depends on
    effort_days: float | None = None  # estimated working days to produce


class Milestone(BaseModel):
    """Quality gate or control point."""

    id: str
    name: str
    is_quality_gate: bool = True
    release_criteria: list[str] = []
    # Scheduling (Phase 3.5): optional dependency and effort hints.
    depends_on: list[str] = []   # ids of milestones/outcomes this depends on
    effort_days: float | None = None  # estimated working days to reach this gate


class Phase(BaseModel):
    """Project phase containing milestones & outcomes."""

    id: str
    name: str
    milestones: list[Milestone]
    outcomes: list[Outcome]


class ProjectPlan(BaseModel):
    """Generated project plan (result of intake + planner)."""

    title: str
    scenario: str
    approach: Approach
    phases: list[Phase]
    roles: list[str]
    open_assumptions: list[str] = []
    risks: list[str] = []


# --------------------------------------------------------------------------- #
# Intake & planning (Phase 2)
# --------------------------------------------------------------------------- #
class RiskItem(BaseModel):
    """A single, fully-articulated project risk (nested in PlanEnrichment).

    Kept flat (no self-references) so the client's ``_flatten_schema`` can
    inline it as ``list[RiskItem]`` for grammar-constrained generation.
    """

    description: str
    impact: str
    likelihood: str
    mitigation: str
    residual_risk: str
    owner: str


class IntakeResult(BaseModel):
    """Structured result of the Socratic intake interview.

    Populated partly by the router (classify + extract pre-answered fields)
    and partly by the deterministic question engine. Flat schema.
    """

    project_id: str
    project_type: str
    objectives: list[str] = []
    scope: list[str] = []
    boundaries: list[str] = []
    stop_criteria: list[str] = []
    constraints: list[str] = []
    success_metrics: list[str] = []
    known_unknowns: list[str] = []
    stakeholders: list[str] = []
    # Sizing answers that drive conditional deliverables (e.g. high_protection_need).
    sizing_flags: dict[str, bool] = {}


class PlanEnrichment(BaseModel):
    """The ONLY LLM ``structured()`` target in the planner.

    The deterministic skeleton already guarantees mandatory outcomes and
    quality gates; enrichment adds judgement (approach, roles, risks,
    assumptions, per-phase tailoring). Flat schema (nested ``list[RiskItem]``
    is inlined by the client).
    """

    approach: Approach
    roles: list[str]
    risks: list[RiskItem]
    assumptions: list[str]
    phase_tailoring_notes: dict[str, str]


# --------------------------------------------------------------------------- #
# Rubric critic / judge output (spec section 4I)
# --------------------------------------------------------------------------- #
class Severity(str, Enum):
    """Finding severity."""

    blocker = "blocker"  # blocks sign-off / acceptance
    major = "major"  # significant gap, rework before sign-off
    minor = "minor"  # improvement, non-blocking


class Verdict(str, Enum):
    """Overall review verdict."""

    pass_ = "pass"
    pass_with_comments = "pass_with_comments"
    fail = "fail"


class Finding(BaseModel):
    """One atomic rubric finding (nested inside ReviewResult)."""

    criterion_id: str
    dimension: str
    result: Literal["pass", "partial", "fail"]
    severity: Severity | None = None
    location: str  # where in the document
    evidence_quote: str  # verbatim text
    rationale: str  # CoT — appears BEFORE result in prompt order
    fix_suggestion: str  # concrete, actionable
    confidence: float  # = self-consistency sample agreement


class ReviewResult(BaseModel):
    """Aggregated rubric review over a deliverable."""

    rubric_id: str
    rubric_version: str
    deliverable_type: str
    findings: list[Finding]
    dimension_summary: dict[str, str]
    blockers: int
    majors: int
    minors: int
    verdict: Verdict
    verdict_rationale: str


# --------------------------------------------------------------------------- #
# Deterministic completeness checker output (Phase 2)
# --------------------------------------------------------------------------- #
class Flag(BaseModel):
    """A single deterministic completeness violation (no LLM involved)."""

    kind: Literal["missing_outcome", "unassigned_role", "ungated_phase"]
    detail: str
    severity: Severity


class CheckReport(BaseModel):
    """Result of ``check_plan`` — pure logic, fully deterministic."""

    project_id: str
    ok: bool
    flags: list[Flag] = []
