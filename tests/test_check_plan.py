"""Deterministic completeness checker tests — [AC2]."""

from hermes_assistant.hermes.model import IntakeResult, ProjectPlan
from hermes_assistant.hermes.planner import build_skeleton, check_plan
from hermes_assistant.hermes.project_types import load_project_type


def _intake(**kw: object) -> IntakeResult:
    base: dict = {"project_id": "p1", "project_type": "isds-analyse",
                  "objectives": ["Assess the ISDS"]}
    base.update(kw)
    return IntakeResult(**base)


def _plan(intake: IntakeResult) -> ProjectPlan:
    return build_skeleton(intake, load_project_type("isds-analyse"))


def test_clean_plan_has_no_flags() -> None:
    """A freshly built skeleton passes the checker cleanly."""
    intake = _intake()
    pt = load_project_type("isds-analyse")
    report = check_plan(_plan(intake), pt, intake)
    assert report.ok is True
    assert report.flags == []


def test_missing_outcome_and_role_yield_two_flags() -> None:
    """[AC2] Removing the schutzbedarf outcome and the ISBO role => two flags."""
    intake = _intake()
    pt = load_project_type("isds-analyse")
    plan = _plan(intake)

    # Inject the two defects.
    for phase in plan.phases:
        phase.outcomes = [oc for oc in phase.outcomes if oc.id != "schutzbedarf"]
    plan.roles = [r for r in plan.roles if r != "ISBO"]

    report = check_plan(plan, pt, intake)
    assert report.ok is False
    assert len(report.flags) == 2
    kinds = {f.kind for f in report.flags}
    assert kinds == {"missing_outcome", "unassigned_role"}
    missing = next(f for f in report.flags if f.kind == "missing_outcome")
    unassigned = next(f for f in report.flags if f.kind == "unassigned_role")
    assert "schutzbedarf" in missing.detail
    assert "ISBO" in unassigned.detail


def test_missing_only_outcome_yields_one_flag() -> None:
    """A single defect yields exactly one flag of the right kind."""
    intake = _intake()
    pt = load_project_type("isds-analyse")
    plan = _plan(intake)
    for phase in plan.phases:
        phase.outcomes = [oc for oc in phase.outcomes if oc.id != "massnahmen"]
    report = check_plan(plan, pt, intake)
    assert [f.kind for f in report.flags] == ["missing_outcome"]


def test_conditional_outcome_required_when_flag_set() -> None:
    """With high_protection_need, a plan lacking restrisiko_freigabe is flagged."""
    intake = _intake(sizing_flags={"high_protection_need": True})
    pt = load_project_type("isds-analyse")
    plan = _plan(intake)
    # Drop the conditional outcome the skeleton just added.
    for phase in plan.phases:
        phase.outcomes = [oc for oc in phase.outcomes if oc.id != "restrisiko_freigabe"]
    report = check_plan(plan, pt, intake)
    assert any(f.kind == "missing_outcome" and "restrisiko_freigabe" in f.detail
               for f in report.flags)
