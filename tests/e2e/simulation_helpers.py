"""Shared helper utilities for Phase 2 E2E simulation tests.

Provides factory functions and store-level helpers that let each simulation
checkpoint test focus on *what* it asserts rather than *how* to set up state.

All helpers are headless (no browser/Playwright dependency). They operate
directly against the Risk Registry, Plan Editor, and Suggestion Store.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

from hermes_assistant.plans.editor import PlanEditor
from hermes_assistant.plans.model import PlanItem, PlanItemStatus, PlanVersion
from hermes_assistant.risks.model import RiskSeverity, RiskStatus
from hermes_assistant.risks.registry import RiskRegistry
from hermes_assistant.suggestions.store import SuggestionStore


# ---------------------------------------------------------------------------
# Named container for simulation stores
# ---------------------------------------------------------------------------


class SimStores(NamedTuple):
    """Lightweight container returned by setup helpers."""

    reg: RiskRegistry
    editor: PlanEditor
    sugg: SuggestionStore
    plan_id: str


# ---------------------------------------------------------------------------
# Project setup
# ---------------------------------------------------------------------------


def setup_project_from_fixture(
    tmp_path: Path,
    fixture_dir: Path,
    *,
    items_per_phase: int = 2,
    author: str = "consultant",
) -> SimStores:
    """Initialise isolated stores and seed a plan from an intake.json fixture.

    Creates one PlanItem per phase per ``items_per_phase`` counter, using
    the fixture's phase list.  Returns a :class:`SimStores` tuple.

    The fixture directory must contain ``intake.json`` with at least::

        {"project_id": "...", "phases": [{"title": "Phase Name"}, ...]}
    """
    intake = json.loads((fixture_dir / "intake.json").read_text())
    plan_id: str = intake["project_id"]
    reg = RiskRegistry(tmp_path / "risks.db")
    editor = PlanEditor(tmp_path / "plans.db")
    sugg = SuggestionStore(tmp_path / "suggestions.db")

    items: list[PlanItem] = []
    order = 0
    for phase in intake["phases"]:
        for i in range(items_per_phase):
            items.append(
                PlanItem(
                    title=f"{phase['title']} task {i + 1}",
                    phase=phase["title"],
                    order=order,
                )
            )
            order += 1
    editor.create(plan_id, items, author=author)
    return SimStores(reg=reg, editor=editor, sugg=sugg, plan_id=plan_id)


def setup_saas_project(tmp_path: Path) -> SimStores:
    """Set up the SaaS MVP simulation from its fixture directory."""
    fixture_dir = Path(__file__).parent / "fixtures" / "saas_mvp"
    plan_data = json.loads((fixture_dir / "plan_v1.json").read_text())
    reg = RiskRegistry(tmp_path / "risks.db")
    editor = PlanEditor(tmp_path / "plans.db")
    sugg = SuggestionStore(tmp_path / "suggestions.db")
    items = [PlanItem(**item) for item in plan_data["items"]]
    editor.create(plan_data["plan_id"], items, author=plan_data["author"])
    return SimStores(reg=reg, editor=editor, sugg=sugg, plan_id=plan_data["plan_id"])


def setup_enterprise_project(tmp_path: Path) -> SimStores:
    """Set up the Enterprise Migration simulation from its fixture directory."""
    fixture_dir = Path(__file__).parent / "fixtures" / "enterprise_migration"
    return setup_project_from_fixture(
        tmp_path, fixture_dir, items_per_phase=2, author="lead-consultant"
    )


def setup_mobile_project(tmp_path: Path) -> SimStores:
    """Set up the Mobile Redesign simulation from its fixture directory."""
    fixture_dir = Path(__file__).parent / "fixtures" / "mobile_redesign"
    return setup_project_from_fixture(
        tmp_path, fixture_dir, items_per_phase=3, author="pm"
    )


# ---------------------------------------------------------------------------
# Risk registry helpers
# ---------------------------------------------------------------------------


def get_open_risks(reg: RiskRegistry) -> list:
    """Return all risks with status=open."""
    return reg.list(status=RiskStatus.open)


def get_critical_risks(reg: RiskRegistry) -> list:
    """Return all risks with severity=critical."""
    return reg.list(severity=RiskSeverity.critical)


def get_accepted_risks(reg: RiskRegistry) -> list:
    """Return all risks with status=accepted."""
    return reg.list(status=RiskStatus.accepted)


def accept_all_open_risks(reg: RiskRegistry, author: str = "consultant") -> list:
    """Accept every currently open risk and return the accepted list.

    The ``author`` parameter is recorded in the risk's ``owner`` field if the
    risk has no existing owner.
    """
    accepted = []
    for risk in reg.list(status=RiskStatus.open):
        if not risk.owner:
            reg.update(risk.id, owner=author)
        reg.accept(risk.id)
        accepted.append(risk.id)
    return accepted


# ---------------------------------------------------------------------------
# Plan editor helpers
# ---------------------------------------------------------------------------


def extend_phase_duration(
    editor: PlanEditor,
    plan_id: str,
    phase_name: str,
    *,
    author: str = "consultant",
) -> PlanVersion:
    """Mark all items in ``phase_name`` as blocked and save a new plan version.

    Models the real workflow where an obstacle (team absence, vendor delay)
    blocks a phase and forces a replanning event.
    """
    latest = editor.get(plan_id)
    assert latest is not None, f"Plan {plan_id!r} not found"
    updated = []
    for item in latest.items:
        if item.phase == phase_name:
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
    return editor.update(plan_id, updated, author=author)


def add_phase(
    editor: PlanEditor,
    plan_id: str,
    phase_name: str,
    task_titles: list[str],
    *,
    assignee: str = "",
    author: str = "consultant",
) -> PlanVersion:
    """Append new tasks under a new phase and save a new plan version.

    Models adding an unplanned sprint (e.g. CVE patch sprint, soft-launch gate).
    """
    latest = editor.get(plan_id)
    assert latest is not None, f"Plan {plan_id!r} not found"
    base_order = max((i.order for i in latest.items), default=-1) + 1
    new_items = list(latest.items) + [
        PlanItem(
            title=title,
            phase=phase_name,
            assignee=assignee,
            order=base_order + idx,
        )
        for idx, title in enumerate(task_titles)
    ]
    return editor.update(plan_id, new_items, author=author)


# ---------------------------------------------------------------------------
# Suggestion helpers
# ---------------------------------------------------------------------------


def apply_suggestion(
    sugg: SuggestionStore,
    editor: PlanEditor,
    plan_id: str,
    text: str,
    confidence: float,
    *,
    new_task_title: str | None = None,
    new_task_phase: str | None = None,
    parent_job_id: str | None = None,
    author: str = "consultant",
) -> tuple:
    """Store a suggestion, optionally add a plan item, and mark it applied.

    Returns ``(Suggestion, PlanVersion)`` — the suggestion record with
    ``applied=True`` and the new plan version.
    """
    s = sugg.add(text, confidence, parent_job_id=parent_job_id)

    latest = editor.get(plan_id)
    assert latest is not None, f"Plan {plan_id!r} not found"
    if new_task_title and new_task_phase:
        base_order = max((i.order for i in latest.items), default=-1) + 1
        new_items = list(latest.items) + [
            PlanItem(title=new_task_title, phase=new_task_phase, order=base_order)
        ]
    else:
        new_items = list(latest.items)

    new_version = editor.update(plan_id, new_items, author=author)
    applied = sugg.apply(s.id, plan_id=plan_id, plan_version=new_version.version)
    return applied, new_version


# ---------------------------------------------------------------------------
# Audit-trail helper
# ---------------------------------------------------------------------------


def audit_trail_summary(
    reg: RiskRegistry,
    editor: PlanEditor,
    plan_id: str,
) -> dict:
    """Return a compact summary dict for end-of-simulation audit assertions.

    Keys:
        risk_count       – total risks ever recorded
        open_count       – risks still open
        accepted_count   – risks accepted
        mitigated_count  – risks mitigated/resolved
        plan_versions    – number of plan versions saved
        authors          – set of authors who saved plan versions
    """
    all_risks = reg.list()
    versions = editor.list_versions(plan_id)
    return {
        "risk_count": len(all_risks),
        "open_count": len([r for r in all_risks if r.status is RiskStatus.open]),
        "accepted_count": len([r for r in all_risks if r.status is RiskStatus.accepted]),
        "mitigated_count": len(
            [r for r in all_risks if r.status is RiskStatus.mitigated]
        ),
        "plan_versions": len(versions),
        "authors": {v.author for v in versions},
    }
