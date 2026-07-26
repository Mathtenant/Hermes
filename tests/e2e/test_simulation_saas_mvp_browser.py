"""E2E simulation: SaaS MVP Launch — 30-day project with 6 checkpoints.

Drives a headless (store-level) simulation of a junior consultant working
through a realistic SaaS launch project. No browser/Playwright dependency
— all assertions run against the Risk Registry, Plan Editor, and
Suggestion Store directly.

Checkpoints:
  Day 0   — Project intake; plan v1 seeded from fixture; stores confirmed empty
  Day 5   — Architecture review flags security gap; risk auto-created
  Day 10  — Lead dev absence extends Phase 2; plan v2 saved
  Day 15  — Testing review fails; suggestions applied; plan v3 created
  Day 18  — CVE patch sprint added; plan v4 created; red risk detected
  Day 28  — Pre-launch sign-off; residual risks accepted
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

_FIXTURES = Path(__file__).parent / "fixtures" / "saas_mvp"


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def sim(tmp_path: Path):
    """Isolated stores + plan loaded from fixture file."""
    reg = RiskRegistry(tmp_path / "risks.db")
    editor = PlanEditor(tmp_path / "plans.db")
    sugg = SuggestionStore(tmp_path / "suggestions.db")

    plan_data = json.loads((_FIXTURES / "plan_v1.json").read_text())
    items = [PlanItem(**item) for item in plan_data["items"]]
    editor.create(plan_data["plan_id"], items, author=plan_data["author"])

    yield {"reg": reg, "editor": editor, "sugg": sugg, "plan_id": plan_data["plan_id"]}

    reg.close()
    editor.close()
    sugg.close()


# ---------------------------------------------------------------------------
# Checkpoint Day 0 — Project intake
# ---------------------------------------------------------------------------


def test_day0_plan_v1_created_from_fixture(sim) -> None:
    """Day 0: plan v1 must exist with 18 items and 7 phases."""
    editor: PlanEditor = sim["editor"]
    v1 = editor.get(sim["plan_id"])
    assert v1 is not None
    assert v1.version == 1
    assert len(v1.items) == 18
    phases = {item.phase for item in v1.items}
    assert len(phases) == 7


def test_day0_risk_registry_starts_empty(sim) -> None:
    """Day 0: no risks pre-exist."""
    reg: RiskRegistry = sim["reg"]
    assert reg.list() == []


# ---------------------------------------------------------------------------
# Checkpoint Day 5 — Architecture review flags security gap
# ---------------------------------------------------------------------------


def test_day5_security_risk_auto_created(sim) -> None:
    """Day 5: auto_create from architecture review text creates a medium+ risk."""
    reg: RiskRegistry = sim["reg"]
    text = (
        "Encryption implementation required\n"
        "Missing data-at-rest encryption for PII fields. High impact if unresolved."
    )
    r = reg.auto_create(text)
    assert r.title == "Encryption implementation required"
    assert r.severity in (RiskSeverity.high, RiskSeverity.critical)
    assert r.status is RiskStatus.open


def test_day5_owner_assigned_and_status_set_to_mitigating(sim) -> None:
    """Day 5: junior assigns owner → status transitions to mitigated (in-progress)."""
    reg: RiskRegistry = sim["reg"]
    r = reg.auto_create(
        "Encryption implementation required\n"
        "High impact — use AWS KMS for all PII."
    )
    updated = reg.update(r.id, owner="alice", status=RiskStatus.mitigated)
    assert updated.owner == "alice"
    assert updated.status is RiskStatus.mitigated


# ---------------------------------------------------------------------------
# Checkpoint Day 10 — Lead dev absence extends Phase 2
# ---------------------------------------------------------------------------


def test_day10_plan_v2_extends_backend_phase(sim) -> None:
    """Day 10: extend Backend Development items → plan v2 captured."""
    editor: PlanEditor = sim["editor"]
    plan_id = sim["plan_id"]
    v1 = editor.get(plan_id)
    assert v1 is not None

    updated = []
    for item in v1.items:
        if item.phase == "Backend Development":
            updated.append(
                PlanItem(
                    id=item.id,
                    title=item.title,
                    phase=item.phase,
                    assignee=item.assignee,
                    role=item.role,
                    status=PlanItemStatus.blocked,
                    order=item.order,
                )
            )
        else:
            updated.append(item)
    v2 = editor.update(plan_id, updated, author="junior-consultant")
    assert v2.version == 2
    blocked = [i for i in v2.items if i.phase == "Backend Development"]
    assert all(i.status is PlanItemStatus.blocked for i in blocked)


def test_day10_plan_diff_shows_backend_change(sim) -> None:
    """Day 10: diff v1→v2 shows changed items (no added/removed)."""
    editor: PlanEditor = sim["editor"]
    plan_id = sim["plan_id"]
    v1 = editor.get(plan_id)
    assert v1 is not None
    backend_items = [
        PlanItem(
            id=item.id, title=item.title, phase=item.phase,
            assignee=item.assignee, role=item.role,
            status=PlanItemStatus.blocked, order=item.order,
        )
        if item.phase == "Backend Development"
        else item
        for item in v1.items
    ]
    editor.update(plan_id, backend_items, author="junior-consultant")
    diff = editor.diff(plan_id, 1, 2)
    assert diff.added == []
    assert diff.removed == []
    assert len(diff.changed) > 0


# ---------------------------------------------------------------------------
# Checkpoint Day 15 — Testing review fails; apply top suggestion
# ---------------------------------------------------------------------------


def test_day15_suggestion_applied_creates_plan_v3(sim) -> None:
    """Day 15: apply suggestion 'Add 2 weeks for integration testing' → plan v3."""
    editor: PlanEditor = sim["editor"]
    sugg: SuggestionStore = sim["sugg"]
    plan_id = sim["plan_id"]

    # Seed v2 first
    v1 = editor.get(plan_id)
    assert v1 is not None
    editor.update(plan_id, v1.items, author="junior-consultant")

    s = sugg.add("Add 2 weeks for integration testing", confidence=0.95, parent_job_id="job-test-001")
    new_items = list(v1.items)
    new_items.append(
        PlanItem(title="Extended integration testing", phase="Testing & QA", assignee="grace")
    )
    v3 = editor.update(plan_id, new_items, author="junior-consultant")
    sugg.apply(s.id, plan_id=plan_id, plan_version=v3.version)

    applied = sugg.get(s.id)
    assert applied is not None
    assert applied.applied is True
    assert applied.plan_version == v3.version
    assert v3.version >= 3


def test_day15_suggestion_confidence_ordering(sim) -> None:
    """Day 15: suggestions sorted by confidence descending."""
    sugg: SuggestionStore = sim["sugg"]
    sugg.add("Add 2 weeks for integration testing", confidence=0.95, parent_job_id="job-001")
    sugg.add("Hire QA contractor", confidence=0.67, parent_job_id="job-001")
    sugg.add("Implement automated UI tests", confidence=0.67, parent_job_id="job-001")

    all_s = sugg.list(parent_job_id="job-001", min_confidence=0.6)
    assert all_s[0].confidence >= all_s[1].confidence


# ---------------------------------------------------------------------------
# Checkpoint Day 18 — CVE patch sprint; risk escalation
# ---------------------------------------------------------------------------


def test_day18_red_risk_created_for_cve_patch(sim) -> None:
    """Day 18: critical CVE creates a high-severity risk entry."""
    reg: RiskRegistry = sim["reg"]
    r = reg.create(
        "Critical CVE in auth dependency",
        description="CVE-2026-9999 allows auth bypass via JWT signature skip.",
        severity=RiskSeverity.critical,
    )
    assert r.severity is RiskSeverity.critical
    assert r.status is RiskStatus.open
    crits = reg.list(severity=RiskSeverity.critical)
    assert any(ri.id == r.id for ri in crits)


def test_day18_plan_v4_adds_security_patch_phase(sim) -> None:
    """Day 18: add 'Security Patch Sprint' items → plan v4."""
    editor: PlanEditor = sim["editor"]
    plan_id = sim["plan_id"]
    v1 = editor.get(plan_id)
    assert v1 is not None
    editor.update(plan_id, v1.items, author="bot")  # v2
    editor.update(plan_id, v1.items, author="bot")  # v3
    patch_items = list(v1.items) + [
        PlanItem(title="Apply CVE patch", phase="Security Patch Sprint", assignee="alice"),
        PlanItem(title="Regression test after patch", phase="Security Patch Sprint", assignee="grace"),
    ]
    v4 = editor.update(plan_id, patch_items, author="junior-consultant")
    patch_phase = [i for i in v4.items if i.phase == "Security Patch Sprint"]
    assert len(patch_phase) == 2


# ---------------------------------------------------------------------------
# Checkpoint Day 28 — Pre-launch sign-off; accept residual risks
# ---------------------------------------------------------------------------


def test_day28_residual_risks_accepted(sim) -> None:
    """Day 28: junior accepts two residual risks; status → accepted."""
    reg: RiskRegistry = sim["reg"]
    r1 = reg.create("Team untested on scale-up", severity=RiskSeverity.medium)
    r2 = reg.create("Post-launch SLA monitoring incomplete", severity=RiskSeverity.low)
    reg.accept(r1.id)
    reg.accept(r2.id)
    accepted = reg.list(status=RiskStatus.accepted)
    accepted_ids = {r.id for r in accepted}
    assert r1.id in accepted_ids
    assert r2.id in accepted_ids


def test_day28_plan_history_has_multiple_versions(sim) -> None:
    """Day 28: plan history has grown throughout the simulation."""
    editor: PlanEditor = sim["editor"]
    plan_id = sim["plan_id"]
    v1 = editor.get(plan_id)
    assert v1 is not None
    # Add versions 2–4 as the simulation progressed
    for _ in range(3):
        editor.update(plan_id, v1.items, author="junior-consultant")
    versions = editor.list_versions(plan_id)
    assert len(versions) >= 4
