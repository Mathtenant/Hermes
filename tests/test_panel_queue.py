"""Phase P5c tests — Job.panel column, enqueue, migration, worker routing, CLI flag.

All tests are offline (in-memory SQLite, mock worker review function).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import patch

from hermes_assistant.hermes.model import ReviewResult
from hermes_assistant.jobqueue.jobs import JobStore
from hermes_assistant.jobqueue.worker import Worker

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _mem_store() -> JobStore:
    return JobStore(":memory:")


def _fake_review(rubric: Any) -> ReviewResult:
    """Build a minimal all-pass ReviewResult."""
    from hermes_assistant.agents.critic import aggregate
    from hermes_assistant.hermes.model import Finding
    findings = [
        Finding(
            criterion_id=c.id,
            dimension=c.dimension.value,
            result="pass",
            severity=None,
            location="",
            evidence_quote="",
            rationale="test",
            fix_suggestion="",
            confidence=1.0,
        )
        for c in rubric.criteria
    ]
    return aggregate(rubric, findings)


# --------------------------------------------------------------------------- #
# Migration tests
# --------------------------------------------------------------------------- #

def test_db_migration_pre_p5_fixture(tmp_path: Path) -> None:
    """A pre-P5 jobs table (no panel column) is migrated on JobStore open.

    Simulate a pre-P5 database by creating the table without the panel column,
    inserting an old-style row, then opening with the new JobStore.
    Old jobs should be readable with panel=False.
    """
    db_path = tmp_path / "old.db"
    # Create an old-style DB manually (no panel column)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            deliverable_path TEXT NOT NULL,
            rubric_id TEXT NOT NULL,
            rubric_version TEXT,
            samples INTEGER NOT NULL DEFAULT 3,
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            result_json TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        INSERT INTO jobs VALUES (
            'abc123', 'review', 'pending', '/tmp/doc.md',
            'project-plan', '1', 3, 0, 3, NULL, NULL,
            '2025-01-01T00:00:00', '2025-01-01T00:00:00'
        )
    """)
    conn.commit()
    conn.close()

    # Open with the new JobStore — migration should add panel column
    store = JobStore(db_path)
    info = store._conn.execute("PRAGMA table_info(jobs)").fetchall()
    col_names = [row[1] for row in info]
    assert "panel" in col_names, "Migration did not add panel column"

    # Old job is readable with panel=False (the migration default)
    job = store.get("abc123")
    assert job is not None
    assert job.panel is False
    store.close()


# --------------------------------------------------------------------------- #
# Enqueue tests
# --------------------------------------------------------------------------- #

def test_enqueue_panel_true() -> None:
    """Enqueue with panel=True stores panel=True in DB."""
    store = _mem_store()
    job = store.enqueue("doc.md", "project-plan", panel=True)
    assert job.panel is True

    fetched = store.get(job.id)
    assert fetched is not None
    assert fetched.panel is True


def test_enqueue_panel_default() -> None:
    """Enqueue without panel kwarg defaults to panel=False."""
    store = _mem_store()
    job = store.enqueue("doc.md", "project-plan")
    assert job.panel is False

    fetched = store.get(job.id)
    assert fetched is not None
    assert fetched.panel is False


# --------------------------------------------------------------------------- #
# Worker routing tests
# --------------------------------------------------------------------------- #

def test_worker_default_review_panel_path(tmp_path: Path) -> None:
    """Worker calls panel_module.panel_review when job.panel=True."""
    store = _mem_store()
    deliverable = tmp_path / "doc.md"
    deliverable.write_text("test content", encoding="utf-8")

    job = store.enqueue(str(deliverable), "project-plan", panel=True)
    job = store.claim_next()  # type: ignore[assignment]
    assert job is not None

    from hermes_assistant.rubrics.loader import load_rubric
    rubric = load_rubric("project-plan")
    fake = _fake_review(rubric)

    worker = Worker(store, logs_dir=tmp_path)
    with patch(
        "hermes_assistant.jobqueue.worker.panel_module.panel_review",
        return_value=fake,
    ) as mock_pr:
        worker.process(job)
    mock_pr.assert_called_once()


def test_worker_default_review_single_path(tmp_path: Path) -> None:
    """Worker calls critic.review when job.panel=False."""
    store = _mem_store()
    deliverable = tmp_path / "doc.md"
    deliverable.write_text("test content", encoding="utf-8")

    job = store.enqueue(str(deliverable), "project-plan", panel=False)
    job = store.claim_next()  # type: ignore[assignment]
    assert job is not None

    from hermes_assistant.rubrics.loader import load_rubric
    rubric = load_rubric("project-plan")
    fake = _fake_review(rubric)

    worker = Worker(store, logs_dir=tmp_path)
    with patch(
        "hermes_assistant.jobqueue.worker.review",
        return_value=fake,
    ) as mock_r:
        worker.process(job)
    mock_r.assert_called_once()


# --------------------------------------------------------------------------- #
# CLI test
# --------------------------------------------------------------------------- #

def test_cli_review_panel_flag(tmp_path: Path) -> None:
    """hermes review --panel <file> enqueues a job with panel=True."""
    from typer.testing import CliRunner

    from hermes_assistant.cli import app

    deliverable = tmp_path / "doc.md"
    deliverable.write_text("some plan text", encoding="utf-8")
    db_path = tmp_path / "jobs.db"

    runner = CliRunner()
    store = JobStore(str(db_path))
    with patch("hermes_assistant.cli._job_store", return_value=store):
        result = runner.invoke(
            app,
            ["review", str(deliverable), "--panel"],
            catch_exceptions=False,
        )
    assert result.exit_code == 0, result.output

    # Verify the job was enqueued with panel=True
    store2 = JobStore(str(db_path))
    jobs = store2.list()
    assert len(jobs) == 1
    assert jobs[0].panel is True
