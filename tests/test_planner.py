"""Planner skeleton + hybrid build tests — the deterministic part of [AC1]."""

from hermes_assistant.hermes.model import (
    Approach,
    IntakeResult,
    PlanEnrichment,
    ProjectPlan,
    RiskItem,
)
from hermes_assistant.hermes.planner import build_plan, build_skeleton
from hermes_assistant.hermes.project_types import load_project_type

MANDATORY = {"informatikschutzobjekt", "schutzbedarf", "risikoanalyse", "massnahmen"}


def _intake(**kw: object) -> IntakeResult:
    base: dict = {"project_id": "p1", "project_type": "isds-analyse",
                  "objectives": ["Assess the ISDS"]}
    base.update(kw)
    return IntakeResult(**base)


def test_skeleton_contains_all_mandatory_outcomes() -> None:
    """[AC1] The skeleton materialises every mandatory outcome as mandatory."""
    pt = load_project_type("isds-analyse")
    plan = build_skeleton(_intake(), pt)
    outcomes = {oc.id: oc for ph in plan.phases for oc in ph.outcomes}
    assert MANDATORY <= set(outcomes)
    assert all(outcomes[i].mandatory for i in MANDATORY)


def test_skeleton_is_schema_valid_projectplan() -> None:
    """[AC1] The skeleton round-trips through ProjectPlan validation."""
    pt = load_project_type("isds-analyse")
    plan = build_skeleton(_intake(), pt)
    reparsed = ProjectPlan.model_validate_json(plan.model_dump_json())
    assert isinstance(reparsed, ProjectPlan)
    assert set(pt.min_roles) <= set(reparsed.roles)


def test_skeleton_phases_have_quality_gates() -> None:
    """Every phase carries at least one quality-gate milestone."""
    pt = load_project_type("isds-analyse")
    plan = build_skeleton(_intake(), pt)
    assert plan.phases and all(
        any(m.is_quality_gate for m in ph.milestones) for ph in plan.phases
    )


def test_conditional_outcome_appears_with_flag() -> None:
    """A sizing flag promotes the conditional deliverable into the skeleton."""
    pt = load_project_type("isds-analyse")
    plan = build_skeleton(_intake(sizing_flags={"high_protection_need": True}), pt)
    ids = {oc.id for ph in plan.phases for oc in ph.outcomes}
    assert "restrisiko_freigabe" in ids


def test_build_plan_offline_returns_valid_skeleton() -> None:
    """[AC1] With no client, build_plan returns the schema-valid skeleton."""
    pt = load_project_type("isds-analyse")
    plan = build_plan(_intake(), pt, client=None)
    ids = {oc.id for ph in plan.phases for oc in ph.outcomes}
    assert MANDATORY <= ids


class _FakeEnrichClient:
    def __init__(self, enrichment: PlanEnrichment) -> None:
        self.enrichment = enrichment

    def structured(self, model: str, messages: list, schema: type) -> PlanEnrichment:
        return self.enrichment


def _enrichment() -> PlanEnrichment:
    return PlanEnrichment(
        approach=Approach.hybrid,
        roles=["ISBO", "Datenschutzberater"],
        risks=[RiskItem(description="Data breach", impact="high", likelihood="medium",
                        mitigation="encryption", residual_risk="low", owner="ISBO")],
        assumptions=["Budget fixed"],
        phase_tailoring_notes={"analysis": "Focus on Schutzbedarf"},
    )


def test_enrichment_merges_without_dropping_mandatory() -> None:
    """Enrichment adds roles/risks/approach but never removes mandatory outcomes."""
    pt = load_project_type("isds-analyse")
    plan = build_plan(_intake(), pt, client=_FakeEnrichClient(_enrichment()))
    ids = {oc.id for ph in plan.phases for oc in ph.outcomes}
    assert MANDATORY <= ids
    assert plan.approach is Approach.hybrid
    # Minimum roles come first; enrichment roles are unioned in.
    assert set(pt.min_roles) <= set(plan.roles)
    assert "Datenschutzberater" in plan.roles
    assert plan.risks and "Data breach" in plan.risks[0]


class _BoomClient:
    def structured(self, model: str, messages: list, schema: type) -> PlanEnrichment:
        raise RuntimeError("ollama down")


def test_enrichment_failure_falls_back_to_skeleton() -> None:
    """[AC1] Any enrichment error yields the valid skeleton, not an exception."""
    pt = load_project_type("isds-analyse")
    plan = build_plan(_intake(), pt, client=_BoomClient())
    ids = {oc.id for ph in plan.phases for oc in ph.outcomes}
    assert MANDATORY <= ids
    assert set(pt.min_roles) <= set(plan.roles)
