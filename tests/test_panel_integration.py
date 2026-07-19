"""Phase P5b tests — panel_check_criterion and panel_review.

All tests are deterministic and offline. A PanelCallRecorder fakes the client,
scripting specific responses per (model, criterion_id) so vote counting and
ordering logic can be verified without a live model.
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import patch

import pytest

from hermes_assistant.agents.critic import CheckSample
from hermes_assistant.agents.panel import (
    panel_check_criterion,
    panel_review,
)
from hermes_assistant.hermes.model import Finding, ReviewResult, Severity
from hermes_assistant.llm.client import OllamaConnectionError
from hermes_assistant.rubrics.model import Criterion, Dimension, Rubric

# --------------------------------------------------------------------------- #
# Mini rubric and helpers
# --------------------------------------------------------------------------- #

def _cs(result: str, quote: str = "verbatim quote here") -> CheckSample:
    return CheckSample(
        location="section 1",
        evidence_quote=quote,
        rationale="because",
        result=result,  # type: ignore[arg-type]
        severity=Severity.minor,
        fix_suggestion="fix it",
    )


def _mini_rubric(n: int = 3) -> Rubric:
    """A mini rubric with ``n`` criteria (evidence_required=False for simplicity)."""
    criteria = [
        Criterion(
            id=f"c{i}",
            dimension=Dimension.completeness,
            text=f"criterion {i}",
            check_type="binary",
            severity_if_failed=Severity.blocker,
            evidence_required=False,
        )
        for i in range(n)
    ]
    return Rubric(
        rubric_id="mini",
        version="1",
        deliverable_type="Thing",
        criteria=criteria,
        anti_patterns=[],
    )


def _evidence_rubric() -> Rubric:
    """A single-criterion rubric with evidence_required=True."""
    return Rubric(
        rubric_id="evidence-test",
        version="1",
        deliverable_type="Thing",
        criteria=[
            Criterion(
                id="c_ev",
                dimension=Dimension.completeness,
                text="some criterion needing evidence",
                check_type="binary",
                severity_if_failed=Severity.blocker,
                evidence_required=True,
            )
        ],
        anti_patterns=[],
    )


def _fake_review_result(rubric: Rubric) -> ReviewResult:
    """Build a minimal all-pass ReviewResult for the given rubric."""
    from hermes_assistant.agents.critic import aggregate
    findings = [
        Finding(
            criterion_id=c.id,
            dimension=c.dimension.value,
            result="pass",
            severity=None,
            location="",
            evidence_quote="",
            rationale="fallback single-judge",
            fix_suggestion="",
            confidence=1.0,
        )
        for c in rubric.criteria
    ]
    return aggregate(rubric, findings)


def _extract_criterion_id(messages: list[dict[str, str]]) -> str:
    """Parse the criterion id from the criterion_messages user prompt."""
    for msg in messages:
        if msg.get("role") == "user":
            m = re.search(r"CRITERION \[([^\]]+)\]", msg["content"])
            if m:
                return m.group(1)
    return "unknown"


# --------------------------------------------------------------------------- #
# PanelCallRecorder — scripted fake client for panel tests
# --------------------------------------------------------------------------- #

class PanelCallRecorder:
    """A fake SampleClient that records all calls and returns scripted samples.

    ``responses`` maps ``(model_id, criterion_id)`` → ``CheckSample``, or just
    ``model_id`` → ``CheckSample`` as a default for any criterion from that model.
    ``failures`` is a set of ``(model_id, criterion_id)`` pairs that should
    raise ``OllamaConnectionError``.
    """

    def __init__(
        self,
        responses: dict[Any, CheckSample],
        failures: set[tuple[str, str]] | None = None,
    ) -> None:
        self.responses = responses
        self.failures: set[tuple[str, str]] = failures or set()
        # Records: (model, criterion_id, keep_alive)
        self.call_log: list[tuple[str, str, int | str | None]] = []

    def structured(
        self,
        model: str,
        messages: list[dict[str, str]],
        schema: type,
        *,
        temperature: float = 0.1,
        num_ctx: int = 4096,
        keep_alive: int | str | None = None,
        **kwargs: object,
    ) -> CheckSample:
        cid = _extract_criterion_id(messages)
        self.call_log.append((model, cid, keep_alive))

        if (model, cid) in self.failures:
            raise OllamaConnectionError(f"scripted failure: {model}/{cid}")

        # Look up (model, cid) first, then model alone, then "default".
        sample = (
            self.responses.get((model, cid))
            or self.responses.get(model)
            or self.responses.get("default")
        )
        if sample is None:
            raise OllamaConnectionError(f"no scripted response for {model}/{cid}")
        return sample


# --------------------------------------------------------------------------- #
# panel_check_criterion tests
# --------------------------------------------------------------------------- #

DELIVERABLE = "verbatim quote here in the document text"


def test_panel_check_criterion_majority() -> None:
    """3 panelists {pass, pass, fail} → pass, confidence ≈ 2/3."""
    rubric = _evidence_rubric()
    crit = rubric.criteria[0]

    client = PanelCallRecorder({
        "qwen3:8b": _cs("pass", quote=DELIVERABLE),
        "gemma3:4b": _cs("pass", quote=DELIVERABLE),
        "llama3.1:8b": _cs("fail", quote=DELIVERABLE),
    })

    finding, trace = panel_check_criterion(
        DELIVERABLE, crit, rubric, client,
        panelists=["qwen3:8b", "gemma3:4b", "llama3.1:8b"],
    )

    assert finding.result == "pass"
    assert finding.confidence == pytest.approx(2.0 / 3.0, abs=1e-3)
    assert trace["criterion_id"] == "c_ev"
    assert set(trace["panelists"]) == {"qwen3:8b", "gemma3:4b", "llama3.1:8b"}


def test_panel_check_criterion_evidence_verification() -> None:
    """Panelist with unverifiable evidence is neutralized to pass.

    qwen fails with fabricated evidence (not in doc) → neutralized to pass.
    gemma fails with real evidence → stays fail.
    llama passes.

    Final: {pass(neutralized), fail, pass} → 2 pass vs 1 fail → pass.
    """
    rubric = _evidence_rubric()
    crit = rubric.criteria[0]
    doc = "The plan has a quality gate for each phase."

    client = PanelCallRecorder({
        # qwen votes fail but evidence not in doc → neutralized to pass
        "qwen3:8b": _cs("fail", quote="FABRICATED EVIDENCE NOT IN DOC"),
        # gemma votes fail with real evidence → stays fail
        "gemma3:4b": _cs("fail", quote="The plan has a quality gate"),
        # llama votes pass
        "llama3.1:8b": _cs("pass", quote="The plan has a quality gate"),
    })

    finding, trace = panel_check_criterion(
        doc, crit, rubric, client,
        panelists=["qwen3:8b", "gemma3:4b", "llama3.1:8b"],
    )

    # qwen neutralized → pass; gemma=fail; llama=pass → 2 pass vs 1 fail → pass
    assert finding.result == "pass"
    # qwen's vote should show as pass in the trace (neutralized)
    assert trace["votes"]["qwen3:8b"] == "pass"
    assert trace["votes"]["gemma3:4b"] == "fail"


# --------------------------------------------------------------------------- #
# panel_review tests
# --------------------------------------------------------------------------- #

def test_panel_review_model_outer_ordering() -> None:
    """Call sequence must be model-outer: all criteria for m1, then m2, then m3."""
    rubric = _mini_rubric(3)
    panelists = ["m1", "m2", "m3"]

    client = PanelCallRecorder({"default": _cs("pass")})

    panel_review(
        "doc text", rubric, client,
        panelists=panelists, min_judges=1,
    )

    # Extract (model, criterion) pairs (ignore keep_alive for ordering check)
    pairs = [(m, c) for m, c, _ in client.call_log]
    expected = [(m, f"c{i}") for m in panelists for i in range(3)]
    assert pairs == expected, f"Expected model-outer ordering, got: {pairs}"


def test_panel_review_first_call_panelist_drop() -> None:
    """Panelist that fails on criterion 0 is dropped from the entire review.

    qwen fails on c0 → dropped. gemma and llama succeed.
    With min_judges=2 and 2 surviving, aggregation proceeds normally.
    """
    rubric = _mini_rubric(2)

    client = PanelCallRecorder(
        responses={"default": _cs("pass")},
        failures={("qwen3:8b", "c0")},
    )

    traces: list[dict[str, Any]] = []
    result = panel_review(
        "doc text", rubric, client,
        panelists=["qwen3:8b", "gemma3:4b", "llama3.1:8b"],
        min_judges=2,
        on_criterion=traces.append,
    )

    # qwen was dropped — it should not appear in any criterion trace
    for trace in traces:
        assert "qwen3:8b" not in trace["panelists"]

    # 2 surviving panelists — normal aggregation (not fallback)
    assert all(t["fallback"] is None for t in traces)
    assert isinstance(result, ReviewResult)


def test_panel_review_min_judges_fallback() -> None:
    """All panelists fail on criterion 0 → min_judges unmet → fallback to single-judge."""
    rubric = _mini_rubric(2)

    # Fail ALL models on criterion 0
    client = PanelCallRecorder(
        responses={"default": _cs("pass")},
        failures={
            ("qwen3:8b", "c0"),
            ("gemma3:4b", "c0"),
            ("llama3.1:8b", "c0"),
        },
    )

    traces: list[dict[str, Any]] = []
    fake_result = _fake_review_result(rubric)

    with patch("hermes_assistant.agents.panel._critic_review", return_value=fake_result) as mock_cr:
        result = panel_review(
            "doc text", rubric, client,
            panelists=["qwen3:8b", "gemma3:4b", "llama3.1:8b"],
            min_judges=2,
            on_criterion=traces.append,
        )
        mock_cr.assert_called_once()

    # Fallback traces should indicate self_consistency fallback
    assert all(t["fallback"] == "self_consistency" for t in traces)
    assert result is fake_result


def test_panel_review_keep_alive_sent() -> None:
    """keep_alive=0 is sent on the last criterion call for each panelist."""
    rubric = _mini_rubric(3)
    panelists = ["qwen3:8b", "gemma3:4b", "llama3.1:8b"]

    client = PanelCallRecorder({"default": _cs("pass")})

    panel_review(
        "doc text", rubric, client,
        panelists=panelists, min_judges=1,
    )

    # For each model, find their last call; it should have keep_alive=0
    for model_id in panelists:
        model_calls = [(c, ka) for m, c, ka in client.call_log if m == model_id]
        assert model_calls, f"No calls for {model_id}"
        last_cid, last_ka = model_calls[-1]
        assert last_ka == 0, (
            f"Last call for {model_id} (criterion {last_cid}) "
            f"expected keep_alive=0, got {last_ka}"
        )
        # All non-last calls should have keep_alive=None
        for cid, ka in model_calls[:-1]:
            assert ka is None, (
                f"Non-last call for {model_id}/{cid} expected keep_alive=None, got {ka}"
            )


def test_panel_review_on_criterion_trace() -> None:
    """on_criterion callback receives a correctly-structured trace dict."""
    rubric = _mini_rubric(1)
    panelists = ["qwen3:8b", "gemma3:4b"]

    client = PanelCallRecorder({
        "qwen3:8b": _cs("pass"),
        "gemma3:4b": _cs("pass"),
    })

    traces: list[dict[str, Any]] = []
    panel_review(
        "doc text", rubric, client,
        panelists=panelists, min_judges=1,
        on_criterion=traces.append,
    )

    assert len(traces) == 1
    t = traces[0]

    # Required keys
    required_keys = {
        "criterion_id", "panelists", "votes", "weights",
        "confidence", "degraded", "unanimous", "fallback",
    }
    assert required_keys == set(t.keys()), f"Unexpected keys: {set(t.keys())}"

    # Content checks
    assert t["criterion_id"] == "c0"
    assert set(t["panelists"]) == {"qwen3:8b", "gemma3:4b"}
    assert t["votes"] == {"qwen3:8b": "pass", "gemma3:4b": "pass"}
    assert t["unanimous"] is True
    assert t["degraded"] is False
    assert t["fallback"] is None
    assert isinstance(t["confidence"], float)


def test_panel_review_degraded_flag() -> None:
    """Panelist failing on a non-first criterion sets degraded=True for that criterion."""
    rubric = _mini_rubric(3)  # c0, c1, c2
    # gemma fails on c1 (not c0 → not dropped, but c1 is degraded)
    client = PanelCallRecorder(
        responses={"default": _cs("pass")},
        failures={("gemma3:4b", "c1")},
    )

    traces: list[dict[str, Any]] = []
    panel_review(
        "doc text", rubric, client,
        panelists=["qwen3:8b", "gemma3:4b", "llama3.1:8b"],
        min_judges=2,
        on_criterion=traces.append,
    )

    trace_by_cid = {t["criterion_id"]: t for t in traces}

    # c0 and c2: all 3 panelists voted → not degraded
    assert trace_by_cid["c0"]["degraded"] is False
    assert trace_by_cid["c2"]["degraded"] is False

    # c1: gemma missing → only 2 of 3 voted → degraded
    assert trace_by_cid["c1"]["degraded"] is True
    assert "gemma3:4b" not in trace_by_cid["c1"]["panelists"]
