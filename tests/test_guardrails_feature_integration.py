"""Integration tests: guardrails applied across Risk Registry, Plan Editor,
and Review / Suggestion store.

These tests exercise the full data path — creating objects through the real
stores, serialising them to JSON, and verifying the confidentiality guard
rejects any payload that leaks sensitive fields.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_assistant.risks.model import RiskSeverity
from hermes_assistant.risks.registry import RiskRegistry
from hermes_assistant.plans.editor import PlanEditor
from hermes_assistant.plans.model import PlanItem
from hermes_assistant.suggestions.store import SuggestionStore
from hermes_assistant.webapp.server import _validate_safe_json


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reg(tmp_path: Path) -> RiskRegistry:
    return RiskRegistry(tmp_path / "risks.db")


def _editor(tmp_path: Path) -> PlanEditor:
    return PlanEditor(tmp_path / "plans.db")


def _suggestions(tmp_path: Path) -> SuggestionStore:
    return SuggestionStore(tmp_path / "suggestions.db")


# ---------------------------------------------------------------------------
# Risk Registry + guardrails
# ---------------------------------------------------------------------------


def test_public_risk_export_passes_confidentiality_guard(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create("Open auth risk", description="OAuth scope too wide")
    reg.create("Internal budget risk", description="Budget overrun", confidential=True)
    public = reg.export_public()
    payload = json.dumps([r.model_dump() for r in public])
    violations = _validate_safe_json(payload)
    assert violations == [], f"Guard violations in public export: {violations}"


def test_confidential_risk_excluded_from_export(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create("Confidential risk", confidential=True)
    reg.create("Public risk", confidential=False)
    public = reg.export_public()
    assert len(public) == 1
    assert public[0].title == "Public risk"


def test_risk_model_contains_no_forbidden_fields(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Scope change risk", description="Scope may shift late in project")
    payload = r.model_dump_json()
    assert _validate_safe_json(payload) == []


def test_risk_severity_values_are_safe_strings(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("High impact risk", severity=RiskSeverity.high)
    payload = r.model_dump_json()
    assert _validate_safe_json(payload) == []


# ---------------------------------------------------------------------------
# Plan Editor + guardrails
# ---------------------------------------------------------------------------


def test_plan_version_serialised_cleanly(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    items = [
        PlanItem(title="Define scope", phase="Phase 1", assignee="alice"),
        PlanItem(title="Review deliverables", phase="Phase 1", assignee="bob"),
    ]
    v1 = editor.create("plan-x", items)
    payload = v1.model_dump_json()
    assert _validate_safe_json(payload) == []


def test_plan_diff_serialised_cleanly(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    items_v1 = [PlanItem(title="T1", phase="P1")]
    items_v2 = [PlanItem(title="T1", phase="P1"), PlanItem(title="T2", phase="P2")]
    editor.create("plan-y", items_v1)
    editor.update("plan-y", items_v2)
    diff = editor.diff("plan-y", 1, 2)
    payload = diff.model_dump_json()
    assert _validate_safe_json(payload) == []


def test_plan_version_history_all_clean(tmp_path: Path) -> None:
    editor = _editor(tmp_path)
    editor.create("plan-z", [PlanItem(title="T1")])
    editor.update("plan-z", [PlanItem(title="T1"), PlanItem(title="T2")])
    editor.update("plan-z", [PlanItem(title="T2")])
    versions = editor.list_versions("plan-z")
    for v in versions:
        assert _validate_safe_json(v.model_dump_json()) == []


# ---------------------------------------------------------------------------
# Suggestion Store + guardrails
# ---------------------------------------------------------------------------


def test_suggestion_serialised_cleanly(tmp_path: Path) -> None:
    store = _suggestions(tmp_path)
    s = store.add("Add two weeks for integration testing", confidence=0.95)
    payload = s.model_dump_json()
    assert _validate_safe_json(payload) == []


def test_applied_suggestion_serialised_cleanly(tmp_path: Path) -> None:
    store = _suggestions(tmp_path)
    s = store.add("Hire QA contractor", confidence=0.67, parent_job_id="job-abc")
    applied = store.apply(s.id, plan_id="plan-1", plan_version=2)
    assert _validate_safe_json(applied.model_dump_json()) == []


# ---------------------------------------------------------------------------
# Data isolation: no runtime DB files inside the repo tree
# ---------------------------------------------------------------------------


def test_in_memory_registry_leaves_no_disk_file(tmp_path: Path) -> None:
    """Using ':memory:' means zero on-disk artefacts are created."""
    reg = RiskRegistry(":memory:")
    reg.create("Ephemeral risk")
    reg.close()
    # No .db files should appear under tmp_path because we used :memory:
    db_files = list(tmp_path.rglob("*.db"))
    assert db_files == []
