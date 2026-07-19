"""Pre-mortem agent unit tests (offline — no live model required).

All model calls are intercepted by fake clients so the suite runs without
Ollama.  Tests cover: happy path, graceful degradation, trace logging,
fallback cascade, prompt override, and RiskItem field completeness.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from hermes_assistant.agents.redteam import PreMortemPass, run_premortem
from hermes_assistant.cli import app
from hermes_assistant.config import settings
from hermes_assistant.hermes.model import (
    Milestone,
    Outcome,
    Phase,
    ProjectPlan,
    RiskItem,
)
from hermes_assistant.llm.client import OllamaConnectionError
from hermes_assistant.llm.tracing import JsonlTracer

runner = CliRunner()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _risk_item(**kwargs: Any) -> RiskItem:
    defaults: dict[str, str] = dict(
        description="Budget overrun",
        impact="Project cancelled",
        likelihood="Medium",
        mitigation="Weekly budget reviews",
        residual_risk="Low",
        owner="PM",
    )
    defaults.update(kwargs)  # type: ignore[arg-type]
    return RiskItem(**defaults)


def _minimal_plan() -> ProjectPlan:
    return ProjectPlan(
        title="Test Project",
        scenario="IT modernisation for finance",
        approach="traditional",
        phases=[
            Phase(
                id="initiation",
                name="Initiation",
                milestones=[
                    Milestone(id="ms1", name="Kick-off", is_quality_gate=True)
                ],
                outcomes=[
                    Outcome(
                        id="oc1",
                        name="Project Charter",
                        kind="document",
                        mandatory=True,
                        module="m",
                    )
                ],
            )
        ],
        roles=["PM", "Dev"],
        open_assumptions=["Budget is 100 k CHF", "Team size = 3"],
        risks=["Budget overrun", "Scope creep"],
    )


class _FakeClient:
    """Returns a canned PreMortemPass; records which models were called."""

    def __init__(self, risks: list[RiskItem]) -> None:
        self._risks = risks
        self.calls: list[str] = []

    def structured(
        self,
        model: str,
        messages: list[dict[str, str]],
        schema: type[Any],
        *,
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> PreMortemPass:
        self.calls.append(model)
        return PreMortemPass(risks=self._risks)


class _DeadClient:
    """Always raises OllamaConnectionError."""

    def structured(
        self,
        model: str,
        messages: list[dict[str, str]],
        schema: type[Any],
        *,
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> PreMortemPass:
        raise OllamaConnectionError("offline")


class _FlakyClient:
    """Fails on the first call, succeeds on subsequent calls."""

    def __init__(self, risks: list[RiskItem]) -> None:
        self._risks = risks
        self.calls: list[str] = []

    def structured(
        self,
        model: str,
        messages: list[dict[str, str]],
        schema: type[Any],
        *,
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> PreMortemPass:
        self.calls.append(model)
        if len(self.calls) == 1:
            raise OllamaConnectionError("primary down")
        return PreMortemPass(risks=self._risks)


class _CapturingClient:
    """Returns a canned result and exposes the last messages received."""

    def __init__(self, risks: list[RiskItem]) -> None:
        self._risks = risks
        self.last_messages: list[dict[str, str]] = []

    def structured(
        self,
        model: str,
        messages: list[dict[str, str]],
        schema: type[Any],
        *,
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> PreMortemPass:
        self.last_messages = messages
        return PreMortemPass(risks=self._risks)


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
def test_run_premortem_returns_risks() -> None:
    risks = [_risk_item(), _risk_item(description="Scope creep")]
    client = _FakeClient(risks)
    result = run_premortem(_minimal_plan(), client=client)

    assert isinstance(result, PreMortemPass)
    assert len(result.risks) == 2
    assert result.risks[0].description == "Budget overrun"
    assert result.risks[1].description == "Scope creep"


def test_run_premortem_risk_items_have_all_fields() -> None:
    risk = _risk_item()
    assert risk.description
    assert risk.impact
    assert risk.likelihood
    assert risk.mitigation
    assert risk.residual_risk
    assert risk.owner


# --------------------------------------------------------------------------- #
# Graceful offline degradation
# --------------------------------------------------------------------------- #
def test_run_premortem_offline_returns_empty() -> None:
    """When all models fail, the function returns an empty PreMortemPass."""
    result = run_premortem(_minimal_plan(), client=_DeadClient())

    assert isinstance(result, PreMortemPass)
    assert result.risks == []


# --------------------------------------------------------------------------- #
# Traceability logging
# --------------------------------------------------------------------------- #
def test_run_premortem_trace_logged_on_success(tmp_path: Path) -> None:
    tracer = JsonlTracer(tmp_path / "trace.jsonl")
    client = _FakeClient([_risk_item()])
    run_premortem(_minimal_plan(), client=client, tracer=tracer)

    records = tracer.read_all()
    assert len(records) >= 1
    assert records[0].call_type == "structured"
    assert records[0].success is True
    assert records[0].extra.get("agent") == "premortem"


def test_run_premortem_trace_logged_on_failure(tmp_path: Path) -> None:
    """Failed model calls are still traced with success=False."""
    tracer = JsonlTracer(tmp_path / "trace.jsonl")
    run_premortem(_minimal_plan(), client=_DeadClient(), tracer=tracer)

    records = tracer.read_all()
    assert len(records) >= 1
    assert any(r.success is False for r in records)
    assert any(r.extra.get("agent") == "premortem" for r in records)


# --------------------------------------------------------------------------- #
# Fallback cascade
# --------------------------------------------------------------------------- #
def test_run_premortem_fallback_used_when_primary_fails() -> None:
    """Primary model OllamaError → fallback model is attempted and succeeds."""
    risks = [_risk_item()]
    client = _FlakyClient(risks)
    result = run_premortem(_minimal_plan(), client=client)

    assert len(result.risks) == 1
    # Two models were tried: primary (raised) + fallback (succeeded).
    assert len(client.calls) == 2


# --------------------------------------------------------------------------- #
# Prompt override
# --------------------------------------------------------------------------- #
def test_run_premortem_prompt_override_replaces_user_turn() -> None:
    """When prompt_override is given, the user message is set to it verbatim."""
    client = _CapturingClient([_risk_item()])
    run_premortem(_minimal_plan(), prompt_override="Describe failure.", client=client)

    user_messages = [m for m in client.last_messages if m["role"] == "user"]
    assert user_messages, "No user message found"
    assert user_messages[0]["content"] == "Describe failure."


def test_run_premortem_default_prompt_contains_plan_info() -> None:
    """Without an override, the user prompt includes the plan title."""
    plan = _minimal_plan()
    client = _CapturingClient([_risk_item()])
    run_premortem(plan, client=client)

    user_messages = [m for m in client.last_messages if m["role"] == "user"]
    assert plan.title in user_messages[0]["content"]


# --------------------------------------------------------------------------- #
# CLI smoke tests
# --------------------------------------------------------------------------- #
def test_premortem_cmd_plan_not_found_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "projects_path", str(tmp_path))
    result = runner.invoke(app, ["premortem", "no-such-project"])
    assert result.exit_code == 2
    assert "not found" in result.stdout.lower()


def test_premortem_cmd_saves_premortem_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "projects_path", str(tmp_path))
    proj_dir = tmp_path / "myproj"
    proj_dir.mkdir()
    (proj_dir / "plan.json").write_text(
        _minimal_plan().model_dump_json(indent=2), encoding="utf-8"
    )

    fake_result = PreMortemPass(risks=[_risk_item()])
    with patch("hermes_assistant.cli.run_premortem", return_value=fake_result):
        result = runner.invoke(app, ["premortem", "myproj"])

    assert result.exit_code == 0, result.stdout
    saved_file = proj_dir / "premortem.json"
    assert saved_file.is_file()
    saved = PreMortemPass.model_validate_json(
        saved_file.read_text(encoding="utf-8")
    )
    assert len(saved.risks) == 1
    assert saved.risks[0].description == "Budget overrun"


def test_premortem_cmd_offline_prints_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When run_premortem returns empty, the CLI prints a warning and exits 0."""
    monkeypatch.setattr(settings, "projects_path", str(tmp_path))
    proj_dir = tmp_path / "myproj"
    proj_dir.mkdir()
    (proj_dir / "plan.json").write_text(
        _minimal_plan().model_dump_json(indent=2), encoding="utf-8"
    )

    with patch(
        "hermes_assistant.cli.run_premortem",
        return_value=PreMortemPass(risks=[]),
    ):
        result = runner.invoke(app, ["premortem", "myproj"])

    assert result.exit_code == 0
    assert "no failure scenarios" in result.stdout.lower()
