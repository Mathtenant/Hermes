"""CLI tests for the Phase 3 review/jobs/job/worker commands (offline)."""

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from hermes_assistant.agents.critic import CheckSample
from hermes_assistant.cli import app
from hermes_assistant.config import settings
from hermes_assistant.hermes.model import Severity
from hermes_assistant.llm.client import OllamaClient

from .conftest import FIXTURES

runner = CliRunner()
FLAWED_PLAN = FIXTURES / "flawed_plan.md"


@pytest.fixture(autouse=True)
def _isolated_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the queue db & logs at a temp dir for every test."""
    monkeypatch.setattr(settings, "queue_db_path", str(tmp_path / "jobs.db"))
    monkeypatch.setattr(settings, "queue_logs_path", str(tmp_path / "logs"))


def _canned_fail(*_args: Any, **_kwargs: Any) -> CheckSample:
    """A deterministic 'fail' sample with evidence verbatim in flawed_plan.md."""
    return CheckSample(
        location="Initiation",
        evidence_quote="No quality gate defined.",
        rationale="the initiation phase declares no gate",
        result="fail",
        severity=Severity.blocker,
        fix_suggestion="add a quality-gate milestone",
    )


def test_review_enqueues_job() -> None:
    """`hermes review` queues a job and prints its id."""
    result = runner.invoke(app, ["review", str(FLAWED_PLAN), "--rubric", "project-plan"])
    assert result.exit_code == 0, result.stdout
    assert "queued" in result.stdout

    listing = runner.invoke(app, ["jobs"])
    assert listing.exit_code == 0
    assert "pending" in listing.stdout
    assert "project-plan" in listing.stdout


def test_review_missing_file_exit_2() -> None:
    result = runner.invoke(app, ["review", "does-not-exist.md"])
    assert result.exit_code == 2
    assert "not found" in result.stdout.lower()


def test_review_unknown_rubric_exit_2() -> None:
    result = runner.invoke(app, ["review", str(FLAWED_PLAN), "--rubric", "ghost"])
    assert result.exit_code == 2
    assert "unknown rubric" in result.stdout.lower()


def test_job_not_found_exit_2() -> None:
    result = runner.invoke(app, ["job", "deadbeef"])
    assert result.exit_code == 2
    assert "not found" in result.stdout.lower()


def test_jobs_empty() -> None:
    result = runner.invoke(app, ["jobs"])
    assert result.exit_code == 0
    assert "no jobs" in result.stdout.lower()


def test_review_wait_renders_fail_verdict_exit_1(monkeypatch: pytest.MonkeyPatch) -> None:
    """[AC2] review --wait runs the worker inline; a fail verdict exits 1."""
    monkeypatch.setattr(OllamaClient, "structured", _canned_fail)
    result = runner.invoke(
        app, ["review", str(FLAWED_PLAN), "--rubric", "project-plan", "--wait", "-n", "1"]
    )
    assert result.exit_code == 1, result.stdout
    assert "verdict: fail" in result.stdout
    assert "blockers=" in result.stdout


def test_review_then_worker_then_job(monkeypatch: pytest.MonkeyPatch) -> None:
    """[AC2] Full async flow: enqueue -> worker --once -> job shows the result."""
    monkeypatch.setattr(OllamaClient, "structured", _canned_fail)

    enq = runner.invoke(
        app, ["review", str(FLAWED_PLAN), "--rubric", "project-plan", "-n", "1"]
    )
    assert enq.exit_code == 0, enq.stdout
    # "queued job <id> ..." — pull the 12-char id.
    job_id = enq.stdout.split("job", 1)[1].split()[0].strip("[]")

    work = runner.invoke(app, ["worker", "--once"])
    assert work.exit_code == 0, work.stdout
    assert "processed 1 job" in work.stdout

    shown = runner.invoke(app, ["job", job_id])
    assert shown.exit_code == 1  # verdict fail
    assert "verdict: fail" in shown.stdout
    assert "project-plan" in shown.stdout  # findings table title

    # The per-job JSONL traceability log exists (job_id is a 12-char prefix).
    matches = list(Path(settings.queue_logs_path).glob(f"{job_id}*.jsonl"))
    assert matches, "per-job JSONL log not written"
