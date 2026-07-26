"""E2E simulation: Mobile App Redesign — 45-day project with 6 checkpoints.

Headless store-level simulation of a junior consultant managing a mobile app
redesign with design, QA, and business-pressure obstacles.

Checkpoints:
  Day 0   — Project intake; plan seeded from fixture
  Day 7   — Design review flags WCAG accessibility gaps; risks created
  Day 14  — Platform analytics show iOS/Android divergence; plan v2
  Day 21  — QA finds 15 blockers in beta; suggestions for fixes
  Day 28  — Marketing wants early soft launch; scope discussion tracked
  Day 42  — Final launch review; residual risks accepted; plan audit trail
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

_FIXTURES = Path(__file__).parent / "fixtures" / "mobile_redesign"


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


def _build_plan_items() -> list[PlanItem]:
    intake = json.loads((_FIXTURES / "intake.json").read_text())
    items = []
    order = 0
    for phase in intake["phases"]:
        for i in range(3):
            items.append(
                PlanItem(
                    title=f"{phase['title']} task {i + 1}",
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
    editor.create(plan_id, _build_plan_items(), author="pm")
    yield {"reg": reg, "editor": editor, "sugg": sugg, "plan_id": plan_id}
    reg.close()
    editor.close()
    sugg.close()


# ---------------------------------------------------------------------------
# Checkpoint Day 0 — Project intake
# ---------------------------------------------------------------------------


def test_mr_day0_plan_created_with_six_phases(sim) -> None:
    """Day 0: plan v1 covers all 6 redesign phases (18 items, 3 per phase)."""
    editor: PlanEditor = sim["editor"]
    v1 = editor.get(sim["plan_id"])
    assert v1 is not None
    assert v1.version == 1
    phases = {item.phase for item in v1.items}
    assert len(phases) == 6
    assert len(v1.items) == 18


def test_mr_day0_no_risks_yet(sim) -> None:
    reg: RiskRegistry = sim["reg"]
    assert reg.list() == []


# ---------------------------------------------------------------------------
# Checkpoint Day 7 — Design review flags accessibility gaps
# ---------------------------------------------------------------------------


def test_mr_day7_accessibility_risk_auto_created(sim) -> None:
    """Day 7: design review reveals WCAG gaps → high severity risk."""
    reg: RiskRegistry = sim["reg"]
    text = (
        "Accessibility gap: WCAG 2.1 AA compliance not met\n"
        "Major colour contrast failures on primary action buttons. "
        "High risk of App Store rejection."
    )
    r = reg.auto_create(text)
    assert "accessibility" in r.title.lower() or "wcag" in r.title.lower()
    assert r.severity in (RiskSeverity.high, RiskSeverity.critical)


def test_mr_day7_risk_owner_and_mitigation_set(sim) -> None:
    """Day 7: owner assigned and description updated with mitigation plan."""
    reg: RiskRegistry = sim["reg"]
    r = reg.create(
        "Contrast ratio below WCAG AA threshold",
        description="Primary buttons fail 4.5:1 ratio. Fix: redesign colour palette.",
        severity=RiskSeverity.high,
    )
    updated = reg.update(r.id, owner="ux-lead", status=RiskStatus.mitigated)
    assert updated.owner == "ux-lead"
    assert updated.status is RiskStatus.mitigated


# ---------------------------------------------------------------------------
# Checkpoint Day 14 — Platform analytics reveal divergence
# ---------------------------------------------------------------------------


def test_mr_day14_plan_v2_splits_platform_tasks(sim) -> None:
    """Day 14: analytics divergence leads to platform-specific tasks added."""
    editor: PlanEditor = sim["editor"]
    plan_id = sim["plan_id"]
    v1 = editor.get(plan_id)
    assert v1 is not None
    new_items = list(v1.items) + [
        PlanItem(title="iOS-specific gesture handling", phase="iOS Development", order=100),
        PlanItem(title="Android back-navigation audit", phase="Android Development", order=101),
    ]
    v2 = editor.update(plan_id, new_items, author="pm")
    assert v2.version == 2
    diff = editor.diff(plan_id, 1, 2)
    assert len(diff.added) == 2


def test_mr_day14_no_data_loss_across_versions(sim) -> None:
    """Day 14: all original 18 items still present in v2."""
    editor: PlanEditor = sim["editor"]
    plan_id = sim["plan_id"]
    v1 = editor.get(plan_id)
    assert v1 is not None
    v1_ids = {i.id for i in v1.items}
    v2 = editor.update(plan_id, v1.items, author="pm")
    v2_ids = {i.id for i in v2.items}
    assert v1_ids.issubset(v2_ids)


# ---------------------------------------------------------------------------
# Checkpoint Day 21 — QA finds 15 blockers in beta
# ---------------------------------------------------------------------------


def test_mr_day21_fifteen_blocker_risks_created(sim) -> None:
    """Day 21: each QA blocker becomes a tracked risk entry."""
    reg: RiskRegistry = sim["reg"]
    for n in range(15):
        reg.create(f"Beta blocker #{n + 1}", severity=RiskSeverity.high)
    all_risks = reg.list()
    assert len(all_risks) == 15


def test_mr_day21_top_suggestion_applied(sim) -> None:
    """Day 21: suggestion to fix top blocker applied and linked to plan version."""
    editor: PlanEditor = sim["editor"]
    sugg: SuggestionStore = sim["sugg"]
    plan_id = sim["plan_id"]
    v1 = editor.get(plan_id)
    assert v1 is not None
    s = sugg.add(
        "Fix crash on screen rotation (iOS 17 regression)",
        confidence=0.97,
        parent_job_id="qa-beta-001",
    )
    new_items = list(v1.items) + [
        PlanItem(title="Fix iOS 17 rotation crash", phase="QA & Beta Testing", order=200)
    ]
    v_fixed = editor.update(plan_id, new_items, author="ios-dev")
    sugg.apply(s.id, plan_id=plan_id, plan_version=v_fixed.version)
    applied = sugg.get(s.id)
    assert applied is not None
    assert applied.applied is True
    assert applied.plan_version == v_fixed.version


# ---------------------------------------------------------------------------
# Checkpoint Day 28 — Marketing wants early soft launch
# ---------------------------------------------------------------------------


def test_mr_day28_scope_change_risk_documented(sim) -> None:
    """Day 28: scope creep from marketing pressure tracked as a risk."""
    reg: RiskRegistry = sim["reg"]
    r = reg.create(
        "Premature soft launch reduces QA coverage",
        description="Marketing requests soft launch 2 weeks early. Risk: unresolved blockers ship.",
        severity=RiskSeverity.high,
    )
    assert r.status is RiskStatus.open
    assert r.severity is RiskSeverity.high


def test_mr_day28_plan_v3_captures_soft_launch_scope(sim) -> None:
    """Day 28: plan v3 adds soft launch gate task."""
    editor: PlanEditor = sim["editor"]
    plan_id = sim["plan_id"]
    v1 = editor.get(plan_id)
    assert v1 is not None
    editor.update(plan_id, v1.items, author="pm")  # v2
    soft_items = list(v1.items) + [
        PlanItem(title="Soft launch gate (limited rollout)", phase="Release & Monitoring", order=300),
    ]
    v3 = editor.update(plan_id, soft_items, author="pm")
    assert v3.version == 3
    assert any(i.title == "Soft launch gate (limited rollout)" for i in v3.items)


# ---------------------------------------------------------------------------
# Checkpoint Day 42 — Final launch review; sign-off
# ---------------------------------------------------------------------------


def test_mr_day42_residual_risks_accepted(sim) -> None:
    """Day 42: all remaining open risks are accepted before launch."""
    reg: RiskRegistry = sim["reg"]
    r1 = reg.create("Minor UX inconsistency on Android tablets", severity=RiskSeverity.low)
    r2 = reg.create("Analytics event naming not fully standardised", severity=RiskSeverity.low)
    reg.accept(r1.id)
    reg.accept(r2.id)
    accepted = reg.list(status=RiskStatus.accepted)
    accepted_ids = {r.id for r in accepted}
    assert r1.id in accepted_ids
    assert r2.id in accepted_ids


def test_mr_day42_full_audit_trail_captured(sim) -> None:
    """Day 42: plan history captures all major version milestones."""
    editor: PlanEditor = sim["editor"]
    plan_id = sim["plan_id"]
    v1 = editor.get(plan_id)
    assert v1 is not None
    for author in ("design-sprint", "platform-split", "qa-fixes"):
        editor.update(plan_id, v1.items, author=author)
    versions = editor.list_versions(plan_id)
    assert len(versions) >= 4
    authors = {v.author for v in versions}
    assert "design-sprint" in authors
    assert "platform-split" in authors
    assert "qa-fixes" in authors
