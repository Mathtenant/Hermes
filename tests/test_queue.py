"""Job queue tests — enqueue/claim/complete, atomic claim, retry, shutdown."""

from pathlib import Path

from hermes_assistant.agents.critic import CheckSample, review
from hermes_assistant.hermes.model import Severity
from hermes_assistant.jobqueue.jobs import JobStatus, JobStore
from hermes_assistant.jobqueue.worker import Worker
from hermes_assistant.rubrics.loader import load_rubric


def _store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "jobs.db")


def test_enqueue_claim_complete(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job = store.enqueue("doc.md", "project-plan", samples=2)
    assert job.status is JobStatus.pending
    assert job.samples == 2

    claimed = store.claim_next()
    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.status is JobStatus.running
    assert claimed.attempts == 1

    store.complete(job.id, '{"verdict": "fail"}')
    done = store.get(job.id)
    assert done is not None
    assert done.status is JobStatus.done
    assert done.result_json == '{"verdict": "fail"}'


def test_atomic_claim_two_claimers(tmp_path: Path) -> None:
    """With one pending job, only the first claimer wins; the second gets None."""
    store = _store(tmp_path)
    store.enqueue("doc.md", "project-plan")
    first = store.claim_next()
    second = store.claim_next()
    assert first is not None
    assert second is None


def test_claim_is_fifo(tmp_path: Path) -> None:
    """Jobs are claimed oldest-first."""
    store = _store(tmp_path)
    a = store.enqueue("a.md", "project-plan")
    b = store.enqueue("b.md", "project-plan")
    assert store.claim_next().id == a.id  # type: ignore[union-attr]
    assert store.claim_next().id == b.id  # type: ignore[union-attr]


def test_stale_running_requeued(tmp_path: Path) -> None:
    """A job left running (crashed worker) is returned to pending on sweep."""
    store = _store(tmp_path)
    job = store.enqueue("doc.md", "project-plan")
    store.claim_next()  # -> running
    assert store.get(job.id).status is JobStatus.running  # type: ignore[union-attr]

    n = store.requeue_stale()
    assert n == 1
    assert store.get(job.id).status is JobStatus.pending  # type: ignore[union-attr]


def test_transient_retry_returns_to_pending(tmp_path: Path) -> None:
    """A transient failure with attempts left goes back to pending."""
    store = _store(tmp_path)
    job = store.enqueue("doc.md", "project-plan", max_attempts=3)
    store.claim_next()
    updated = store.fail(job.id, "network blip", retry=True)
    assert updated is not None
    assert updated.status is JobStatus.pending
    assert updated.attempts == 1


def test_retry_exhaustion_fails_terminally(tmp_path: Path) -> None:
    """Once attempts reach max_attempts, retry no longer requeues."""
    store = _store(tmp_path)
    job = store.enqueue("doc.md", "project-plan", max_attempts=2)
    for _ in range(2):
        claimed = store.claim_next()
        assert claimed is not None
        store.fail(claimed.id, "net", retry=True)
    final = store.get(job.id)
    assert final is not None
    assert final.status is JobStatus.failed
    assert final.attempts == 2


def test_non_retry_fail_is_terminal(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job = store.enqueue("doc.md", "project-plan")
    store.claim_next()
    updated = store.fail(job.id, "bad schema", retry=False)
    assert updated is not None
    assert updated.status is JobStatus.failed


def test_get_by_prefix(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job = store.enqueue("doc.md", "project-plan")
    assert store.get(job.id[:8]) is not None
    assert store.get("zzzznope") is None


def test_list_filters_by_status(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.enqueue("a.md", "project-plan")
    b = store.enqueue("b.md", "project-plan")
    store.claim_next()  # claims a -> running
    store.complete(b.id, "{}") if False else None  # keep b pending
    assert len(store.list()) == 2
    pending = store.list(JobStatus.pending)
    assert {j.deliverable_path for j in pending} == {"b.md"}


# --------------------------------------------------------------------------- #
# Worker
# --------------------------------------------------------------------------- #
def _fake_review_fn(tmp_path: Path):
    """A review_fn that runs the real critic with a canned fail sample."""

    class FC:
        def structured(self, model, messages, schema, *, temperature=0.1, **kwargs: object):
            return CheckSample(
                location="Phases",
                evidence_quote="No quality gate defined.",
                rationale="missing gate",
                result="fail",
                severity=Severity.blocker,
                fix_suggestion="add a gate",
            )

    def review_fn(job, on_criterion):
        text = Path(job.deliverable_path).read_text(encoding="utf-8")
        return review(
            text, load_rubric(job.rubric_id), FC(),
            samples=job.samples, on_criterion=on_criterion,
        )

    return review_fn


def test_worker_processes_job_and_writes_jsonl(tmp_path: Path) -> None:
    """[AC2] worker --once completes the job and writes a per-criterion JSONL log."""
    doc = tmp_path / "plan.md"
    doc.write_text("# Phases\n## Initiation\nNo quality gate defined.\n", encoding="utf-8")
    store = _store(tmp_path)
    job = store.enqueue(str(doc), "project-plan", samples=1)

    logs = tmp_path / "logs"
    worker = Worker(store, logs_dir=logs, review_fn=_fake_review_fn(tmp_path))
    processed = worker.run(once=True)
    assert processed == 1

    done = store.get(job.id)
    assert done is not None
    assert done.status is JobStatus.done
    assert done.result_json is not None

    log_file = logs / f"{job.id}.jsonl"
    assert log_file.is_file()
    lines = [ln for ln in log_file.read_text().splitlines() if ln.strip()]
    criterion_lines = [ln for ln in lines if '"criterion_id"' in ln]
    rubric = load_rubric("project-plan")
    # Exactly one line per criterion, plus start/summary events.
    assert len(criterion_lines) == len(rubric.criteria)


def test_worker_graceful_shutdown_releases_inflight(tmp_path: Path) -> None:
    """A stop signal arriving after claim releases the job back to pending."""
    store = _store(tmp_path)
    job = store.enqueue("doc.md", "project-plan")
    worker = Worker(store, logs_dir=tmp_path / "logs")

    original = store.claim_next

    def claim_then_stop():
        claimed = original()
        if claimed is not None:
            worker._stop = True  # signal arrives between claim and process
        return claimed

    store.claim_next = claim_then_stop  # type: ignore[method-assign]
    processed = worker.run(once=True)

    assert processed == 0
    released = store.get(job.id)
    assert released is not None
    assert released.status is JobStatus.pending


def test_worker_signal_handler_sets_stop(tmp_path: Path) -> None:
    import signal

    worker = Worker(_store(tmp_path), logs_dir=tmp_path / "logs")
    assert worker._stop is False
    worker._handle_signal(signal.SIGINT, None)
    assert worker._stop is True
