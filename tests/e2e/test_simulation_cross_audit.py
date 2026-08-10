"""Cross-simulation audit and helper-function tests (Phase 2, 10 tests).

Validates properties that hold across *all three* project simulations:
  - isolation between separate stores
  - risk lifecycle state machine (open → mitigated → accepted → closed)
  - plan version immutability
  - suggestion–plan link integrity
  - rubric YAML fixtures are loadable and well-formed
  - simulation_helpers produce correct state
  - audit_trail_summary reflects reality

These tests exercise the simulation_helpers module so that it is covered and
verified as part of the Phase 2 acceptance criteria.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hermes_assistant.plans.model import PlanItem, PlanItemStatus
from hermes_assistant.risks.model import RiskSeverity, RiskStatus
from hermes_assistant.rubrics.model import Rubric

from tests.e2e.simulation_helpers import (
    SimStores,
    accept_all_open_risks,
    add_phase,
    apply_suggestion,
    audit_trail_summary,
    extend_phase_duration,
    get_accepted_risks,
    get_critical_risks,
    get_open_risks,
    setup_enterprise_project,
    setup_mobile_project,
    setup_saas_project,
)

_RUBRICS_DIR = Path(__file__).parent / "fixtures" / "saas_mvp" / "rubrics"


# ---------------------------------------------------------------------------
# Setup fixture reused across tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def saas(tmp_path: Path) -> SimStores:
    stores = setup_saas_project(tmp_path / "saas")
    yield stores
    stores.reg.close()
    stores.editor.close()
    stores.sugg.close()


@pytest.fixture()
def enterprise(tmp_path: Path) -> SimStores:
    stores = setup_enterprise_project(tmp_path / "enterprise")
    yield stores
    stores.reg.close()
    stores.editor.close()
    stores.sugg.close()


@pytest.fixture()
def mobile(tmp_path: Path) -> SimStores:
    stores = setup_mobile_project(tmp_path / "mobile")
    yield stores
    stores.reg.close()
    stores.editor.close()
    stores.sugg.close()


# ---------------------------------------------------------------------------
# Test 1: Three projects are completely isolated from each other
# ---------------------------------------------------------------------------


def test_cross_stores_are_isolated(saas: SimStores, enterprise: SimStores, mobile: SimStores) -> None:
    """Risks created in one project do not bleed into another project's registry."""
    saas.reg.create("SaaS risk", severity=RiskSeverity.high)
    enterprise.reg.create("Enterprise risk", severity=RiskSeverity.critical)

    assert len(saas.reg.list()) == 1
    assert len(enterprise.reg.list()) == 1
    assert len(mobile.reg.list()) == 0


# ---------------------------------------------------------------------------
# Test 2: Risk lifecycle — full state machine traversal
# ---------------------------------------------------------------------------


def test_risk_lifecycle_full_state_machine(saas: SimStores) -> None:
    """Risk transitions: open → mitigated → closed — each state is queryable."""
    reg = saas.reg
    r = reg.create("Auth token expiry not enforced", severity=RiskSeverity.high)

    assert reg.list(status=RiskStatus.open) != []
    reg.mitigate(r.id)
    assert reg.list(status=RiskStatus.mitigated) != []
    assert reg.list(status=RiskStatus.open) == []

    reg.close(r.id)
    assert reg.list(status=RiskStatus.closed) != []
    assert reg.list(status=RiskStatus.mitigated) == []


# ---------------------------------------------------------------------------
# Test 3: Plan version immutability — old versions are unchanged after update
# ---------------------------------------------------------------------------


def test_plan_version_immutability(saas: SimStores) -> None:
    """Updating a plan does not alter the content of previous versions."""
    editor = saas.editor
    plan_id = saas.plan_id
    v1 = editor.get(plan_id)
    assert v1 is not None
    v1_item_ids = {i.id for i in v1.items}

    new_items = list(v1.items) + [
        PlanItem(title="Extra task v2", phase="Architecture & Security Review", order=999)
    ]
    editor.update(plan_id, new_items, author="bot")

    v1_reread = editor.get(plan_id, 1)
    assert v1_reread is not None
    assert {i.id for i in v1_reread.items} == v1_item_ids


# ---------------------------------------------------------------------------
# Test 4: extend_phase_duration helper marks phase items as blocked
# ---------------------------------------------------------------------------


def test_extend_phase_duration_helper(saas: SimStores) -> None:
    """extend_phase_duration marks items in the target phase as blocked."""
    v2 = extend_phase_duration(
        saas.editor, saas.plan_id, "Backend Development", author="pm"
    )
    blocked = [i for i in v2.items if i.phase == "Backend Development"]
    assert len(blocked) > 0
    assert all(i.status is PlanItemStatus.blocked for i in blocked)
    unblocked = [i for i in v2.items if i.phase != "Backend Development"]
    assert all(i.status is not PlanItemStatus.blocked for i in unblocked)


# ---------------------------------------------------------------------------
# Test 5: add_phase helper appends new phase items
# ---------------------------------------------------------------------------


def test_add_phase_helper(saas: SimStores) -> None:
    """add_phase appends tasks under a new phase without removing existing items."""
    v1 = saas.editor.get(saas.plan_id)
    assert v1 is not None
    original_count = len(v1.items)

    v2 = add_phase(
        saas.editor,
        saas.plan_id,
        "Security Patch Sprint",
        ["Apply CVE patch", "Regression tests after patch"],
        author="alice",
    )
    assert v2.version == 2
    patch_items = [i for i in v2.items if i.phase == "Security Patch Sprint"]
    assert len(patch_items) == 2
    assert len(v2.items) == original_count + 2


# ---------------------------------------------------------------------------
# Test 6: apply_suggestion helper creates correct plan–suggestion link
# ---------------------------------------------------------------------------


def test_apply_suggestion_helper_links_plan_version(saas: SimStores) -> None:
    """apply_suggestion returns applied=True and the plan_version is the new version."""
    applied, new_version = apply_suggestion(
        saas.sugg,
        saas.editor,
        saas.plan_id,
        "Add 2 weeks for integration testing",
        confidence=0.95,
        new_task_title="Extended integration testing",
        new_task_phase="Testing & QA",
        parent_job_id="job-test-001",
        author="junior-consultant",
    )
    assert applied.applied is True
    assert applied.plan_id == saas.plan_id
    assert applied.plan_version == new_version.version
    assert applied.parent_job_id == "job-test-001"


# ---------------------------------------------------------------------------
# Test 7: accept_all_open_risks bulk-accepts every open risk
# ---------------------------------------------------------------------------


def test_accept_all_open_risks_helper(saas: SimStores) -> None:
    """accept_all_open_risks closes every open risk and leaves no open risks."""
    reg = saas.reg
    reg.create("Residual risk A", severity=RiskSeverity.low)
    reg.create("Residual risk B", severity=RiskSeverity.low)
    reg.create("Residual risk C", severity=RiskSeverity.medium)

    accepted_ids = accept_all_open_risks(reg, author="pm")
    assert len(accepted_ids) == 3
    assert get_open_risks(reg) == []
    assert len(get_accepted_risks(reg)) == 3


# ---------------------------------------------------------------------------
# Test 8: audit_trail_summary reflects state accurately
# ---------------------------------------------------------------------------


def test_audit_trail_summary_accuracy(saas: SimStores) -> None:
    """audit_trail_summary counts match the actual registry and editor state."""
    reg = saas.reg
    editor = saas.editor
    plan_id = saas.plan_id

    r1 = reg.create("Open issue", severity=RiskSeverity.high)
    r2 = reg.create("Accepted issue", severity=RiskSeverity.low)
    r3 = reg.create("Mitigated issue", severity=RiskSeverity.medium)
    reg.accept(r2.id)
    reg.mitigate(r3.id)

    v1 = editor.get(plan_id)
    assert v1 is not None
    editor.update(plan_id, v1.items, author="sprint-1")
    editor.update(plan_id, v1.items, author="sprint-2")

    summary = audit_trail_summary(reg, editor, plan_id)
    assert summary["risk_count"] == 3
    assert summary["open_count"] == 1
    assert summary["accepted_count"] == 1
    assert summary["mitigated_count"] == 1
    assert summary["plan_versions"] == 3   # v1 from fixture + 2 updates
    assert "sprint-1" in summary["authors"]
    assert "sprint-2" in summary["authors"]


# ---------------------------------------------------------------------------
# Test 9: All four SaaS MVP rubric YAML files are loadable and valid
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rubric_file", ["architecture.yaml", "testing.yaml", "security.yaml", "launch.yaml"])
def test_saas_rubric_yaml_files_are_valid(rubric_file: str) -> None:
    """Each rubric YAML can be loaded and has at least 3 criteria."""
    rubric_path = _RUBRICS_DIR / rubric_file
    assert rubric_path.exists(), f"Missing rubric fixture: {rubric_path}"
    # Fixture files use simple names (not the versioned {id}.v{N}.yaml convention)
    # so we load and validate directly via the Pydantic model.
    raw = yaml.safe_load(rubric_path.read_text(encoding="utf-8")) or {}
    rubric = Rubric.model_validate(raw)
    assert rubric.rubric_id != ""
    assert len(rubric.criteria) >= 3
    # Every criterion must have a non-empty id and text
    for c in rubric.criteria:
        assert c.id
        assert c.text.strip()


# ---------------------------------------------------------------------------
# Test 10: End-to-end audit trail — 3-project combined summary
# ---------------------------------------------------------------------------


def test_combined_audit_trail_all_simulations(
    saas: SimStores, enterprise: SimStores, mobile: SimStores
) -> None:
    """Verify that each simulation maintains an independent, complete audit trail."""
    # SaaS: 4 plan versions, 2 risks (1 accepted, 1 mitigated)
    saas.reg.create("SaaS risk A", severity=RiskSeverity.high)
    r_saas = saas.reg.create("SaaS risk B", severity=RiskSeverity.low)
    saas.reg.accept(r_saas.id)
    v1_s = saas.editor.get(saas.plan_id)
    assert v1_s is not None
    for author in ("saas-v2", "saas-v3", "saas-v4"):
        saas.editor.update(saas.plan_id, v1_s.items, author=author)
    s_summary = audit_trail_summary(saas.reg, saas.editor, saas.plan_id)

    # Enterprise: 3 plan versions, 1 critical risk (mitigated)
    cr = enterprise.reg.create("Critical DB issue", severity=RiskSeverity.critical)
    enterprise.reg.mitigate(cr.id)
    v1_e = enterprise.editor.get(enterprise.plan_id)
    assert v1_e is not None
    for author in ("em-v2", "em-v3"):
        enterprise.editor.update(enterprise.plan_id, v1_e.items, author=author)
    e_summary = audit_trail_summary(enterprise.reg, enterprise.editor, enterprise.plan_id)

    # Mobile: 2 plan versions, 0 risks remaining open
    v1_m = mobile.editor.get(mobile.plan_id)
    assert v1_m is not None
    mobile.editor.update(mobile.plan_id, v1_m.items, author="mobile-v2")
    m_summary = audit_trail_summary(mobile.reg, mobile.editor, mobile.plan_id)

    # SaaS assertions
    assert s_summary["risk_count"] == 2
    assert s_summary["accepted_count"] == 1
    assert s_summary["plan_versions"] == 4
    assert "saas-v4" in s_summary["authors"]

    # Enterprise assertions
    assert e_summary["risk_count"] == 1
    assert e_summary["mitigated_count"] == 1
    assert get_critical_risks(enterprise.reg)[0].status is RiskStatus.mitigated
    assert e_summary["plan_versions"] == 3

    # Mobile assertions
    assert m_summary["risk_count"] == 0
    assert m_summary["plan_versions"] == 2
    assert "mobile-v2" in m_summary["authors"]
