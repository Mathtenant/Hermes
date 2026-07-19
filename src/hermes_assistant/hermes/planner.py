"""Planner — deterministic skeleton + LLM enrichment, and the pure checker.

``build_plan`` is a *skeleton-first hybrid*: it first materialises a fully
schema-valid :class:`ProjectPlan` (phases, quality gates, all mandatory
outcomes, minimum roles) straight from the YAML taxonomy — no model involved —
then makes exactly one ``structured()`` call for a :class:`PlanEnrichment`
(approach, extra roles, risks, assumptions, per-phase notes). If the model is
unavailable the skeleton is returned unchanged, so a valid plan is guaranteed
independent of model behaviour (AC1).

``check_plan`` is pure logic — no model calls — comparing the plan against the
same ``mandatory_deliverables`` resolver the planner used, plus the type's
minimum roles (AC2).
"""

from __future__ import annotations

import logging
from typing import Protocol

from hermes_assistant.hermes.model import (
    Approach,
    CheckReport,
    Flag,
    IntakeResult,
    Milestone,
    Outcome,
    Phase,
    PlanEnrichment,
    ProjectPlan,
    Severity,
)
from hermes_assistant.hermes.project_types import (
    PhaseSpec,
    ProjectType,
    load_phase_spine,
    mandatory_deliverables,
    resolve_phases,
)
from hermes_assistant.library.model import Exemplar
from hermes_assistant.llm.roster import ModelRole, get_model

logger = logging.getLogger(__name__)


class StructuredClient(Protocol):
    """Minimal structural type for the enrichment call (duck-typed in tests).

    Typed to the concrete PlanEnrichment return so a generic OllamaClient
    matches structurally (mypy struggles to match generic protocol methods).
    """

    def structured(
        self, model: str, messages: list[dict[str, str]], schema: type[PlanEnrichment]
    ) -> PlanEnrichment: ...


# --------------------------------------------------------------------------- #
# Deterministic skeleton (no LLM)
# --------------------------------------------------------------------------- #
def build_skeleton(
    intake: IntakeResult,
    pt: ProjectType,
    spine: dict[str, PhaseSpec] | None = None,
) -> ProjectPlan:
    """Build a schema-valid plan from the taxonomy alone — no model calls.

    Every mandatory deliverable becomes a mandatory :class:`Outcome` attached
    to its phase; every phase carries its quality-gate milestones; roles are
    seeded from the type's minimum roles. This is what guarantees AC1.
    """
    spine = spine if spine is not None else load_phase_spine()
    phase_specs = resolve_phases(pt, spine)
    mandatory = mandatory_deliverables(pt, intake.sizing_flags)

    phases: list[Phase] = []
    for spec in phase_specs:
        milestones = [
            Milestone(
                id=ms.id,
                name=ms.name,
                is_quality_gate=ms.is_quality_gate,
                release_criteria=list(ms.release_criteria),
            )
            for ms in spec.milestones
        ]
        outcomes = [
            Outcome(
                id=d.id,
                name=d.name,
                kind=d.kind,
                mandatory=True,
                module=pt.id,
                phase=spec.id,
                condition=d.condition,
            )
            for d in mandatory
            if d.phase == spec.id
        ]
        phases.append(
            Phase(id=spec.id, name=spec.name, milestones=milestones, outcomes=outcomes)
        )

    title = intake.objectives[0] if intake.objectives else pt.name
    return ProjectPlan(
        title=title,
        scenario=pt.name,
        approach=Approach.traditional,
        phases=phases,
        roles=list(pt.min_roles),
        open_assumptions=list(intake.known_unknowns),
        risks=[],
    )


# --------------------------------------------------------------------------- #
# Enrichment merge helpers
# --------------------------------------------------------------------------- #
def _merge_roles(base: list[str], extra: list[str]) -> list[str]:
    """Union preserving order; base (minimum) roles always come first."""
    merged = list(base)
    for role in extra:
        if role not in merged:
            merged.append(role)
    return merged


def _apply_enrichment(plan: ProjectPlan, enrichment: PlanEnrichment) -> ProjectPlan:
    """Fold enrichment into the skeleton without ever dropping mandatory data."""
    plan.approach = enrichment.approach
    plan.roles = _merge_roles(plan.roles, enrichment.roles)
    plan.open_assumptions = list(dict.fromkeys(plan.open_assumptions + enrichment.assumptions))
    plan.risks = [
        f"{r.description} — mitigation: {r.mitigation} (residual: {r.residual_risk}, owner: {r.owner})"
        for r in enrichment.risks
    ]
    for phase in plan.phases:
        note = enrichment.phase_tailoring_notes.get(phase.id)
        if note and phase.milestones:
            phase.milestones[0].release_criteria.append(f"Tailoring: {note}")
    return plan


def _enrichment_messages(
    intake: IntakeResult,
    pt: ProjectType,
    *,
    exemplars: list[Exemplar] | None = None,
) -> list[dict[str, str]]:
    facts = {
        "project_type": pt.name,
        "objectives": intake.objectives,
        "scope": intake.scope,
        "boundaries": intake.boundaries,
        "constraints": intake.constraints,
        "success_metrics": intake.success_metrics,
        "stakeholders": intake.stakeholders,
        "minimum_roles": pt.min_roles,
        "phases": pt.phases,
    }
    exemplar_section = ""
    if exemplars:
        lessons = "\n".join(
            f"- [{ex.id}] {ex.title}: {ex.lesson}"
            + (f" (good: {ex.expected[:80]!r})" if ex.expected else "")
            + (f" (bad: {ex.actual[:80]!r})" if ex.actual else "")
            for ex in exemplars
        )
        exemplar_section = (
            f"\n\nLessons from past-project exemplars (use as risk mitigations):\n"
            f"{lessons}"
        )
    return [
        {
            "role": "system",
            "content": (
                "You are a senior HERMES 2022 project manager. Given the intake "
                "facts, produce a PlanEnrichment: choose an approach, list the "
                "roles (include all minimum roles), enumerate concrete risks with "
                "mitigations and residual risk owners, state open assumptions, and "
                "give a short tailoring note per phase. Return ONLY valid JSON."
                f"{exemplar_section}"
            ),
        },
        {"role": "user", "content": str(facts)},
    ]


# --------------------------------------------------------------------------- #
# Hybrid build (skeleton + one enrichment call)
# --------------------------------------------------------------------------- #
def build_plan(
    intake: IntakeResult,
    pt: ProjectType,
    client: StructuredClient | None = None,
    *,
    spine: dict[str, PhaseSpec] | None = None,
    exemplars: list[Exemplar] | None = None,
) -> ProjectPlan:
    """Deterministic skeleton + one PlanEnrichment call.

    The skeleton is always valid on its own; enrichment is additive. Any model
    or transport failure is logged and swallowed — the skeleton is returned so
    AC1 holds even fully offline.

    ``exemplars`` injects library lessons into the enrichment prompt as risk
    mitigation context (see Phase P2 library loader).
    """
    plan = build_skeleton(intake, pt, spine=spine)
    if client is None:
        return plan
    try:
        enrichment = client.structured(
            get_model(ModelRole.PLANNER),
            _enrichment_messages(intake, pt, exemplars=exemplars),
            PlanEnrichment,
        )
    except Exception as exc:  # noqa: BLE001 — enrichment is best-effort, skeleton stands
        logger.warning("plan enrichment failed, returning skeleton: %s", exc)
        return plan
    return _apply_enrichment(plan, enrichment)


# --------------------------------------------------------------------------- #
# Deterministic completeness checker (no LLM) — AC2
# --------------------------------------------------------------------------- #
def check_plan(plan: ProjectPlan, pt: ProjectType, intake: IntakeResult) -> CheckReport:
    """Flag missing mandatory outcomes and unassigned minimum roles.

    Pure logic against the same ``mandatory_deliverables`` resolver used to
    build the plan. Also flags any phase lacking a quality gate. No model calls.
    """
    flags: list[Flag] = []

    mandatory_ids = {d.id: d for d in mandatory_deliverables(pt, intake.sizing_flags)}
    present_ids = {oc.id for phase in plan.phases for oc in phase.outcomes}
    for oc_id in sorted(mandatory_ids):
        if oc_id not in present_ids:
            spec = mandatory_ids[oc_id]
            flags.append(
                Flag(
                    kind="missing_outcome",
                    detail=f"Mandatory outcome '{spec.name}' ({oc_id}) is absent from the plan",
                    severity=Severity.blocker,
                )
            )

    assigned = set(plan.roles)
    for role in pt.min_roles:
        if role not in assigned:
            flags.append(
                Flag(
                    kind="unassigned_role",
                    detail=f"Minimum role '{role}' is not assigned in the plan",
                    severity=Severity.blocker,
                )
            )

    for phase in plan.phases:
        if not any(ms.is_quality_gate for ms in phase.milestones):
            flags.append(
                Flag(
                    kind="ungated_phase",
                    detail=f"Phase '{phase.name}' ({phase.id}) has no quality gate",
                    severity=Severity.major,
                )
            )

    return CheckReport(project_id=intake.project_id, ok=not flags, flags=flags)
