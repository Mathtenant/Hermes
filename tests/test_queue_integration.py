"""End-to-end async queue review against a live Ollama critic model.

Marked ``integration``; skipped when the critic model is unavailable. This is
the *real* [AC2] check: enqueue a review, drain it with a worker, and confirm
the stored ReviewResult and the per-job JSONL traceability log.

    pytest -m integration
"""

from pathlib import Path

import pytest

from hermes_assistant.agents.critic import resolve_critic_models
from hermes_assistant.config import settings
from hermes_assistant.hermes.model import ReviewResult, Verdict
from hermes_assistant.jobqueue.jobs import JobStatus, JobStore
from hermes_assistant.jobqueue.worker import Worker
from hermes_assistant.llm.client import OllamaClient
from hermes_assistant.rubrics.loader import load_rubric

from .conftest import FIXTURES

pytestmark = pytest.mark.integration

FLAWED_PLAN = FIXTURES / "flawed_plan.md"


@pytest.fixture
def critic_available() -> None:
    """Skip unless Ollama and the critic model are both available."""
    client = OllamaClient(host=settings.ollama_host)
    health = client.health()
    if not health["available"]:
        pytest.skip("Ollama service is not reachable")
    primary, _ = resolve_critic_models(settings.critic_model or None)
    installed = {str(m).split(":")[0] for m in health["models"]}
    if primary.split(":")[0] not in installed:
        pytest.skip(f"critic model {primary} not pulled")


def test_ac2_enqueue_worker_job(
    tmp_path: Path, critic_available: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[AC2] enqueue -> worker --once -> stored ReviewResult + per-job JSONL log."""
    monkeypatch.setattr(settings, "critic_samples", 1)  # keep the real run short
    store = JobStore(tmp_path / "jobs.db")
    logs = tmp_path / "logs"
    job = store.enqueue(str(FLAWED_PLAN), "project-plan", samples=1)

    worker = Worker(store, logs_dir=logs)
    processed = worker.run(once=True)
    assert processed == 1

    done = store.get(job.id)
    assert done is not None
    assert done.status is JobStatus.done
    assert done.result_json is not None

    result = ReviewResult.model_validate_json(done.result_json)
    assert result.verdict is Verdict.fail
    assert result.blockers >= 1

    # Per-job JSONL log: one line per criterion (plus start/summary events).
    log_file = logs / f"{job.id}.jsonl"
    assert log_file.is_file()
    lines = [ln for ln in log_file.read_text().splitlines() if ln.strip()]
    criterion_lines = [ln for ln in lines if '"criterion_id"' in ln]
    assert len(criterion_lines) == len(load_rubric("project-plan").criteria)
