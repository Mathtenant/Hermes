"""Critic unit tests — voting, evidence verification, aggregation, fallback.

All deterministic: the model is a programmable fake returning canned
:class:`CheckSample` rows, so no live Ollama is required.
"""

from hermes_assistant.agents.critic import (
    CheckSample,
    aggregate,
    check_criterion,
    resolve_critic_models,
    review,
    verify_evidence,
    vote,
)
from hermes_assistant.hermes.model import Finding, Severity, Verdict
from hermes_assistant.llm.client import OllamaConnectionError
from hermes_assistant.llm.roster import ModelRole, get_model_config
from hermes_assistant.rubrics.loader import load_rubric
from hermes_assistant.rubrics.model import Criterion, Dimension, Rubric

FLAWED = """# Phases

## Initiation
No quality gate defined.

# Risks

| Data breach | High | TBD | |

# Success Metrics

- Improve security posture
"""


def _sample(result: str, quote: str = "No quality gate defined.", **kw: object) -> CheckSample:
    base: dict = {
        "location": "Phases",
        "evidence_quote": quote,
        "rationale": "reasoning",
        "result": result,
        "severity": Severity.blocker,
        "fix_suggestion": "fix it",
    }
    base.update(kw)
    return CheckSample(**base)  # type: ignore[arg-type]


class FakeClient:
    """Returns a fixed CheckSample; records temperatures used per call."""

    def __init__(self, sample: CheckSample) -> None:
        self.sample = sample
        self.temperatures: list[float] = []

    def structured(self, model: str, messages: list, schema: type, *, temperature: float = 0.1, **kwargs: object):
        self.temperatures.append(temperature)
        return self.sample


class SequenceClient:
    """Returns successive samples from a list (cycles if exhausted)."""

    def __init__(self, samples: list[CheckSample]) -> None:
        self.samples = samples
        self.calls = 0

    def structured(self, model: str, messages: list, schema: type, *, temperature: float = 0.1, **kwargs: object):
        s = self.samples[self.calls % len(self.samples)]
        self.calls += 1
        return s


# --------------------------------------------------------------------------- #
# Evidence verification (hallucination guard)
# --------------------------------------------------------------------------- #
def test_verify_evidence_verbatim_substring() -> None:
    assert verify_evidence("No quality gate defined.", FLAWED)


def test_verify_evidence_whitespace_normalised() -> None:
    """Reflowed whitespace still verifies (both sides normalised)."""
    assert verify_evidence("No   quality\ngate defined.", FLAWED)


def test_verify_evidence_detects_hallucination() -> None:
    """A fabricated quote absent from the document does not verify."""
    assert not verify_evidence("The plan guarantees zero downtime.", FLAWED)


def test_verify_evidence_empty_quote_is_false() -> None:
    assert not verify_evidence("   ", FLAWED)


# --------------------------------------------------------------------------- #
# Voting
# --------------------------------------------------------------------------- #
def test_vote_majority() -> None:
    result, conf = vote([_sample("fail"), _sample("fail"), _sample("pass")])
    assert result == "fail"
    assert conf == 2 / 3


def test_vote_tie_resolves_pessimistically() -> None:
    """A fail/pass tie resolves to fail (fail > partial > pass)."""
    result, conf = vote([_sample("fail"), _sample("pass")])
    assert result == "fail"
    assert conf == 0.5


def test_vote_partial_beats_pass_on_tie() -> None:
    result, _ = vote([_sample("partial"), _sample("pass")])
    assert result == "partial"


def test_vote_empty_is_pass_zero_conf() -> None:
    assert vote([]) == ("pass", 0.0)


# --------------------------------------------------------------------------- #
# CoT field order
# --------------------------------------------------------------------------- #
def test_checksample_field_order_is_cot() -> None:
    """[design] location -> evidence_quote -> rationale precede result."""
    fields = list(CheckSample.model_fields)
    assert fields.index("location") < fields.index("result")
    assert fields.index("evidence_quote") < fields.index("result")
    assert fields.index("rationale") < fields.index("result")


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #
def _finding(result: str, severity: Severity | None, dim: str = "completeness") -> Finding:
    return Finding(
        criterion_id="c",
        dimension=dim,
        result=result,  # type: ignore[arg-type]
        severity=severity,
        location="x",
        evidence_quote="q" if result != "pass" else "",
        rationale="r",
        fix_suggestion="f",
        confidence=1.0,
    )


def test_aggregate_fails_on_blocker() -> None:
    rubric = load_rubric("project-plan")
    result = aggregate(rubric, [_finding("fail", Severity.blocker)])
    assert result.verdict is Verdict.fail
    assert result.blockers == 1


def test_aggregate_fails_on_major() -> None:
    rubric = load_rubric("project-plan")
    result = aggregate(rubric, [_finding("fail", Severity.major)])
    assert result.verdict is Verdict.fail
    assert result.majors == 1


def test_aggregate_pass_with_comments_on_minor() -> None:
    rubric = load_rubric("project-plan")
    result = aggregate(rubric, [_finding("partial", Severity.minor)])
    assert result.verdict is Verdict.pass_with_comments
    assert result.minors == 1


def test_aggregate_all_pass() -> None:
    rubric = load_rubric("project-plan")
    result = aggregate(rubric, [_finding("pass", None), _finding("pass", None)])
    assert result.verdict is Verdict.pass_
    assert result.blockers == result.majors == result.minors == 0


# --------------------------------------------------------------------------- #
# check_criterion — evidence + hallucination guard + severity override
# --------------------------------------------------------------------------- #
def _blocker_criterion() -> Criterion:
    return Criterion(
        id="every_phase_quality_gate",
        dimension=Dimension.completeness,
        text="Every phase has a quality gate.",
        check_type="binary",
        severity_if_failed=Severity.blocker,
        evidence_required=True,
    )


def _mini_rubric() -> Rubric:
    return Rubric(
        rubric_id="mini",
        version="1",
        deliverable_type="Thing",
        criteria=[_blocker_criterion()],
    )


def test_check_criterion_verified_fail_keeps_severity() -> None:
    """A failing finding with verifiable evidence keeps the criterion severity."""
    client = FakeClient(_sample("fail", quote="No quality gate defined."))
    finding, trace = check_criterion(
        FLAWED, _blocker_criterion(), _mini_rubric(), client,
        primary_model="m", samples=3,
    )
    assert finding.result == "fail"
    assert finding.severity is Severity.blocker
    assert finding.evidence_quote in FLAWED
    assert trace["evidence_verified"] is True
    assert trace["hallucination_guard"] is False


def test_check_criterion_hallucination_guard_neutralises() -> None:
    """A fail whose evidence is fabricated is neutralised to pass (not a blocker)."""
    client = FakeClient(_sample("fail", quote="Totally fabricated evidence line."))
    finding, trace = check_criterion(
        FLAWED, _blocker_criterion(), _mini_rubric(), client,
        primary_model="m", samples=3,
    )
    assert finding.result == "pass"
    assert finding.severity is None
    assert trace["hallucination_guard"] is True

    # And it must not count as a blocker after aggregation.
    result = aggregate(load_rubric("project-plan"), [finding])
    assert result.blockers == 0


def test_check_criterion_samples_use_diverse_temperatures() -> None:
    """Sample 1 is low-temp; later samples add diversity (higher temp)."""
    client = FakeClient(_sample("fail"))
    check_criterion(
        FLAWED, _blocker_criterion(), _mini_rubric(), client,
        primary_model="m", samples=3,
    )
    assert client.temperatures[0] == 0.1
    assert all(t > 0.1 for t in client.temperatures[1:])


# --------------------------------------------------------------------------- #
# Fallback model
# --------------------------------------------------------------------------- #
class FlakyClient:
    """Fails on the primary model, succeeds on the fallback."""

    def __init__(self, primary: str, sample: CheckSample) -> None:
        self.primary = primary
        self.sample = sample
        self.models_tried: list[str] = []

    def structured(self, model: str, messages: list, schema: type, *, temperature: float = 0.1, **kwargs: object):
        self.models_tried.append(model)
        if model == self.primary:
            raise OllamaConnectionError("primary down")
        return self.sample


def test_fallback_model_used_when_primary_fails() -> None:
    """When the primary model errors, the critic falls back to another family."""
    client = FlakyClient("primary-model", _sample("fail"))
    finding, trace = check_criterion(
        FLAWED, _blocker_criterion(), _mini_rubric(), client,
        primary_model="primary-model", fallback_model="fallback-model", samples=1,
    )
    assert "fallback-model" in client.models_tried
    assert trace["models"] == ["fallback-model"]
    assert finding.result == "fail"


def test_no_model_output_yields_non_finding() -> None:
    """If every sample fails on both models, the criterion is an honest pass."""

    class DeadClient:
        def structured(self, model, messages, schema, *, temperature=0.1, **kwargs: object):
            raise OllamaConnectionError("all down")

    finding, trace = check_criterion(
        FLAWED, _blocker_criterion(), _mini_rubric(), DeadClient(),
        primary_model="p", fallback_model="f", samples=2,
    )
    assert finding.result == "pass"
    assert finding.confidence == 0.0
    assert trace["sample_results"] == []


def test_resolve_critic_models_defaults_to_roster() -> None:
    """Default judge is the roster CRITIC (family != planner) with its fallback."""
    primary, fallback = resolve_critic_models()
    cfg = get_model_config(ModelRole.CRITIC)
    assert primary == cfg.id
    assert fallback == cfg.fallback
    assert primary != get_model_config(ModelRole.PLANNER).id


# --------------------------------------------------------------------------- #
# review() — full deterministic pipeline (proves AC1 logic offline)
# --------------------------------------------------------------------------- #
def test_review_flawed_plan_verdict_fail_with_blocker() -> None:
    """[AC1-logic] Failing every criterion with verified evidence -> fail, blocker."""
    client = FakeClient(_sample("fail", quote="No quality gate defined."))
    traces: list[dict] = []
    result = review(
        FLAWED, load_rubric("project-plan"), client,
        samples=3, on_criterion=traces.append,
    )
    assert result.verdict is Verdict.fail
    assert result.blockers >= 1
    # Every finding's evidence is a verbatim substring of the document.
    for f in result.findings:
        if f.result != "pass" and f.evidence_quote:
            assert f.evidence_quote in FLAWED
    # One trace per criterion (the JSONL log guarantee).
    assert len(traces) == len(result.findings)
