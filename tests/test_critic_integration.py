"""End-to-end critic review against a live Ollama critic model.

Marked ``integration`` and skipped when Ollama or the critic model is
unavailable, so the default offline suite stays green. Run explicitly:

    pytest -m integration

This is the *real* [AC1] check: reviewing a deliberately flawed plan must yield
verdict=fail with at least one blocker and findings that cite the real defects
with verbatim evidence.
"""

from pathlib import Path

import pytest

from hermes_assistant.agents.critic import resolve_critic_models, review, verify_evidence
from hermes_assistant.config import settings
from hermes_assistant.hermes.model import Verdict
from hermes_assistant.llm.client import OllamaClient
from hermes_assistant.rubrics.loader import load_rubric

from .conftest import FIXTURES

pytestmark = pytest.mark.integration

FLAWED_PLAN = FIXTURES / "flawed_plan.md"


@pytest.fixture
def live_critic() -> OllamaClient:
    """A real client, skipping if Ollama or the critic model is unavailable."""
    client = OllamaClient(host=settings.ollama_host)
    health = client.health()
    if not health["available"]:
        pytest.skip("Ollama service is not reachable")
    primary, _ = resolve_critic_models(settings.critic_model or None)
    installed = {str(m).split(":")[0] for m in health["models"]}
    if primary.split(":")[0] not in installed:
        pytest.skip(f"critic model {primary} not pulled")
    return client


def test_ac1_flawed_plan_verdict_fail(live_critic: OllamaClient) -> None:
    """[AC1] The flawed plan reviews as fail with >=1 blocker and verbatim evidence."""
    text = Path(FLAWED_PLAN).read_text(encoding="utf-8")
    rubric = load_rubric("project-plan")

    result = review(
        text, rubric, live_critic,
        model=settings.critic_model or None,
        samples=settings.critic_samples,
    )

    assert result.verdict is Verdict.fail
    assert result.blockers >= 1

    # Every non-pass finding must quote text that actually appears (no
    # hallucinated evidence survives the guard).
    for finding in result.findings:
        if finding.result != "pass" and finding.evidence_quote:
            assert verify_evidence(finding.evidence_quote, text), (
                f"evidence for {finding.criterion_id} not verbatim: "
                f"{finding.evidence_quote!r}"
            )

    # The known defects should surface among the findings.
    failing_ids = {f.criterion_id for f in result.findings if f.result != "pass"}
    assert "every_phase_quality_gate" in failing_ids
