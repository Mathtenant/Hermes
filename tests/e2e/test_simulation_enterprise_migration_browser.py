"""E2E simulation: Enterprise Data Migration — 60-day project with 6 checkpoints.

Headless store-level simulation of a junior consultant managing a complex
enterprise data migration with multiple obstacles.

Checkpoints:
  Day 0   — Project intake; plan seeded; stores empty
  Day 10  — Audit finds data scope issues; risks created; plan v2
  Day 20  — Vendor delays 3 weeks; plan extended; risk escalated
  Day 30  — Test migration finds data corruption; blocker risk
  Day 40  — Compliance auditor requests evidence; suggestions applied
  Day 55  — Final pre-cutover review; residual risks accepted; audit trail verified
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_assistant.plans.editor import PlanEditor
from hermes_assistant.plans.model import PlanItem, PlanItemStatus
from hermes_assistant.risks.model import RiskSeverity, RiskStatus
from hermes_assistant.risks.registry import RiskRegistry
from hermes_assistant.suggestions.store import SuggestionStore

_FIXTURES = Path(__file__).parent / "fixtures" / "enterprise_migration"


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


def _build_plan_items() -> list[PlanItem]:
    intake = json.loads((_FIXTURES / "intake.json").read_text())
    items = []
    order = 0
    for phase in intake["phases"]:
        items.append(
            PlanItem(
                title=f"{phase['title']} kickoff",
                phase=phase["title"],
                order=order,
            )
        )
        order += 1
        items.append(
            PlanItem(
                title=f"{phase['title']} deliverable",
                phase=phase["title"],
                order=order,
            )
        )
        order += 1
    return items


@pytest.fixture()
def sim(tmp_path: Path):
    intake = json.loads((_FIXTURES / "intake.json").read_text())
    reg = RiskRegistry(tmp_path / "risks.db")
    editor = PlanEditor(tmp_path / "plans.db")
    sugg = SuggestionStore(tmp_path / "suggestions.db")
    plan_id = intake["project_id"]
    editor.create(plan_id, _build_plan_items(), author="lead-consultant")
    yield {"reg": reg, "editor": editor, "sugg": sugg, "plan_id": plan_id}
    reg.close()
    editor.close()
    sugg.close()


# ---------------------------------------------------------------------------
# Checkpoint Day 0 — Project intake
# ---------------------------------------------------------------------------


def test_em_day0_plan_created_with_all_phases(sim) -> None:
    """Day 0: plan v1 covers 6 phases (12 items, 2 per phase)."""
    editor: PlanEditor = sim["editor"]
    v1 = editor.get(sim["plan_id"])
    assert v1 is not None
    assert v1.version == 1
    assert len(v1.items) == 12
    phases = {item.phase for item in v1.items}
    assert len(phases) == 6


def test_em_day0_risk_registry_empty(sim) -> None:
    reg: RiskRegistry = sim["reg"]
    assert reg.list() == []


# ---------------------------------------------------------------------------
# Checkpoint Day 10 — Audit finds data scope issues
# ---------------------------------------------------------------------------


def test_em_day10_data_scope_risk_created(sim) -> None:
    """Day 10: audit reveals undocumented PII tables → high severity risk."""
    reg: RiskRegistry = sim["reg"]
    r = reg.create(
        "Undocumented PII tables in legacy system",
        description="Audit found 3 tables with personal data not in original scope.",
        severity=RiskSeverity.high,
    )
    assert r.severity is RiskSeverity.high
    assert r.status is RiskStatus.open


def test_em_day10_plan_v2_adds_extra_mapping_items(sim) -> None:
    """Day 10: discovery scope expanded → plan v2 with additional items."""
    editor: PlanEditor = sim["editor"]
    plan_id = sim["plan_id"]
    v1 = editor.get(plan_id)
    assert v1 is not None
    extra = [
        PlanItem(title="Audit undocumented PII tables", phase="Data Mapping", order=100),
        PlanItem(title="GDPR remediation for PII tables", phase="Compliance Review", order=101),
    ]
    v2 = editor.update(plan_id, list(v1.items) + extra, author="lead-consultant")
    assert v2.version == 2
    added_diff = editor.diff(plan_id, 1, 2)
    assert len(added_diff.added) == 2


# ---------------------------------------------------------------------------
# Checkpoint Day 20 — Vendor delays 3 weeks
# ---------------------------------------------------------------------------


def test_em_day20_vendor_delay_risk_escalated(sim) -> None:
    """Day 20: vendor delays creates a blocker risk; owner assigned."""
    reg: RiskRegistry = sim["reg"]
    r = reg.create(
        "Vendor ETL tool delivery delayed 3 weeks",
        description="DataMigrate Inc delayed delivery. Migration script phase blocked.",
        severity=RiskSeverity.high,
    )
    updated = reg.update(r.id, owner="lead-consultant", status=RiskStatus.open)
    assert updated.owner == "lead-consultant"
    highs = reg.list(severity=RiskSeverity.high)
    assert len(highs) >= 1


def test_em_day20_plan_v3_reflects_delay(sim) -> None:
    """Day 20: migration scripts phase blocked → new plan version."""
    editor: PlanEditor = sim["editor"]
    plan_id = sim["plan_id"]
    v1 = editor.get(plan_id)
    assert v1 is not None
    blocked = [
        PlanItem(
            id=i.id, title=i.title, phase=i.phase,
            status=PlanItemStatus.blocked, order=i.order,
        )
        if i.phase == "Migration Scripts"
        else i
        for i in v1.items
    ]
    editor.update(plan_id, v1.items)   # v2
    v3 = editor.update(plan_id, blocked, author="lead-consultant")
    assert v3.version == 3
    blocked_items = [i for i in v3.items if i.status is PlanItemStatus.blocked]
    assert len(blocked_items) >= 1


# ---------------------------------------------------------------------------
# Checkpoint Day 30 — Test migration finds data corruption
# ---------------------------------------------------------------------------


def test_em_day30_corruption_risk_is_critical(sim) -> None:
    """Day 30: data corruption in test migration → critical risk created."""
    reg: RiskRegistry = sim["reg"]
    r = reg.auto_create(
        "Critical data corruption detected in test migration\n"
        "15% of financial records have garbled encoding after ETL transform."
    )
    assert r.severity is RiskSeverity.critical


def test_em_day30_suggestion_added_for_corruption_fix(sim) -> None:
    """Day 30: suggestion to fix encoding issue stored with high confidence."""
    sugg: SuggestionStore = sim["sugg"]
    s = sugg.add(
        "Switch ETL encoding from latin-1 to UTF-8 with BOM stripping",
        confidence=0.92,
        parent_job_id="review-corruption-001",
    )
    assert s.confidence == 0.92
    pending = sugg.list(applied=False)
    assert len(pending) >= 1


# ---------------------------------------------------------------------------
# Checkpoint Day 40 — Compliance review; apply suggestion
# ---------------------------------------------------------------------------


def test_em_day40_suggestion_applied_creates_new_version(sim) -> None:
    """Day 40: apply encoding fix suggestion → plan updated."""
    editor: PlanEditor = sim["editor"]
    sugg: SuggestionStore = sim["sugg"]
    plan_id = sim["plan_id"]
    v1 = editor.get(plan_id)
    assert v1 is not None

    s = sugg.add("Rerun test migration with corrected encoding", confidence=0.90)
    new_items = list(v1.items) + [
        PlanItem(title="Re-run test migration (encoding fix)", phase="Test Migration", order=200)
    ]
    v_new = editor.update(plan_id, new_items, author="lead-consultant")
    sugg.apply(s.id, plan_id=plan_id, plan_version=v_new.version)
    applied = sugg.get(s.id)
    assert applied is not None
    assert applied.applied is True
    assert applied.plan_id == plan_id


def test_em_day40_compliance_risks_have_owners(sim) -> None:
    """Day 40: all open risks are assigned owners before compliance review."""
    reg: RiskRegistry = sim["reg"]
    reg.create("GDPR documentation gap", severity=RiskSeverity.medium, owner="compliance-officer")
    reg.create("Retention policy missing", severity=RiskSeverity.medium, owner="compliance-officer")
    owned = reg.list(owner="compliance-officer")
    assert len(owned) == 2


# ---------------------------------------------------------------------------
# Checkpoint Day 55 — Pre-cutover; final sign-off
# ---------------------------------------------------------------------------


def test_em_day55_all_critical_risks_closed_or_accepted(sim) -> None:
    """Day 55: critical risks resolved before cutover."""
    reg: RiskRegistry = sim["reg"]
    crit = reg.create("Network bandwidth insufficient at cutover", severity=RiskSeverity.critical)
    reg.mitigate(crit.id)
    resolved = reg.list(status=RiskStatus.mitigated)
    assert any(r.id == crit.id for r in resolved)


def test_em_day55_audit_trail_complete(sim) -> None:
    """Day 55: plan history shows multiple versions, all with authors."""
    editor: PlanEditor = sim["editor"]
    plan_id = sim["plan_id"]
    v1 = editor.get(plan_id)
    assert v1 is not None
    for label in ("v2-scope", "v3-delay", "v4-encoding"):
        editor.update(plan_id, v1.items, author=label)
    versions = editor.list_versions(plan_id)
    assert len(versions) >= 4
    assert all(v.plan_id == plan_id for v in versions)
