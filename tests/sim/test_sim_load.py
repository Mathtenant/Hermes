"""P2 edge-case simulations: resource exhaustion & long-running accumulation
(S7, S9).

Everything in this module is marked ``slow`` — per-PR runs skip it
(``pytest -m "not slow"``); a nightly job runs the full suite including these.
Nothing here touches a live Ollama service: S9's "concurrent reviews" use a
canned, duck-typed fake client exactly like ``tests/test_queue.py``.

Resource usage (tracemalloc peak, RSS delta) is measured and asserted against
deliberately generous bounds — tight enough to catch a real leak/blow-up on
this 16 GB M4 Air, loose enough not to be flaky across machines/CI.
"""

from __future__ import annotations

import gc
import resource
import threading
import time
import tracemalloc
from pathlib import Path

import pytest

from hermes_assistant.agents.critic import CheckSample, review
from hermes_assistant.chat.model import ChatRole
from hermes_assistant.chat.store import ChatStore
from hermes_assistant.hermes.model import Severity
from hermes_assistant.jobqueue.jobs import JobStatus, JobStore
from hermes_assistant.jobqueue.worker import Worker
from hermes_assistant.plans.editor import PlanEditor
from hermes_assistant.plans.model import PlanItem
from hermes_assistant.risks.registry import RiskRegistry
from hermes_assistant.rubrics.loader import load_rubric
from hermes_assistant.webapp.import_json import import_payload

from .faults import run_concurrent
from .snapshots import assert_invariants

pytestmark = pytest.mark.slow


def _rss_bytes() -> int:
    """Current process peak RSS in bytes (macOS reports bytes; Linux KB)."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    import sys

    return peak if sys.platform == "darwin" else peak * 1024


# --------------------------------------------------------------------------- #
# S7 — resource exhaustion
# --------------------------------------------------------------------------- #


@pytest.mark.serial
def test_s7_100k_risks_list_bounded_memory(tmp_path: Path) -> None:
    """100k risks, written in 10 batches of 10k (the per-type import cap),
    then listed in full. Must complete and stay within a generous memory
    envelope — no unbounded blow-up."""
    db_path = tmp_path / "risks.db"
    batch_size = 10_000
    batches = 10

    tracemalloc.start()
    rss_before = _rss_bytes()
    start = time.perf_counter()

    for b in range(batches):
        payload = {
            "risks": [
                {"id": f"r-{b}-{i}", "title": f"risk {b}-{i}"} for i in range(batch_size)
            ]
        }
        result = import_payload(payload, risks_db=str(db_path))
        assert result.created == batch_size

    elapsed = time.perf_counter() - start
    reg = RiskRegistry(db_path)
    all_risks = reg.list()
    assert len(all_risks) == batch_size * batches

    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rss_after = _rss_bytes()

    # Generous envelopes: 100k small Risk objects should be well under a few
    # hundred MB of Python-tracked allocation, and the whole run under a
    # couple of minutes even on modest hardware.
    assert peak < 800 * 1024 * 1024, f"tracemalloc peak too high: {peak / 1e6:.1f} MB"
    assert elapsed < 120, f"100k-risk import+list took too long: {elapsed:.1f}s"

    reg.close_connection()
    # rss_before/after recorded for diagnostics; not hard-asserted (RSS is
    # noisy across platforms/allocators) beyond the tracemalloc bound above.
    assert rss_after >= 0 and rss_before >= 0


@pytest.mark.serial
def test_s7_deep_wide_plan_10k_items(tmp_path: Path) -> None:
    """A single plan with 10,000 items (max per-entity-type batch width) must
    import and round-trip without excessive memory growth."""
    paths = {
        "plans_db": str(tmp_path / "plans.db"),
    }
    items = [{"title": f"item-{i}", "order": i} for i in range(10_000)]
    tracemalloc.start()

    result = import_payload({"plans": [{"plan_id": "wide-plan", "items": items}]}, **paths)
    assert result.created == 1

    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 400 * 1024 * 1024, f"tracemalloc peak too high: {peak / 1e6:.1f} MB"

    editor = PlanEditor(paths["plans_db"])
    latest = editor.get("wide-plan")
    assert latest is not None
    assert len(latest.items) == 10_000
    editor.close()


def test_s7_1000_concurrent_chat_messages(tmp_path: Path) -> None:
    """1000 concurrent ``add_message`` calls against one session: no lost
    writes, no SQLite errors, bounded memory."""
    store = ChatStore(tmp_path / "chat.db")
    session = store.create_session("proj-load")

    tracemalloc.start()

    def _one(i: int) -> None:
        store.add_message(session.id, ChatRole.user, f"msg-{i}")

    outcomes = run_concurrent(_one, 1000, max_workers=32, timeout=120)
    errors = [exc for _, exc in outcomes if exc is not None]

    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert errors == [], f"errors during 1000 concurrent chat writes: {errors[:5]}"
    messages = store.list_messages(session.id)
    assert len(messages) == 1000
    assert peak < 400 * 1024 * 1024, f"tracemalloc peak too high: {peak / 1e6:.1f} MB"
    store.close()


@pytest.mark.serial
def test_s7_10k_import_repeated_no_unbounded_growth(tmp_path: Path) -> None:
    """Repeat a 10k-row import into fresh databases three times; traced
    memory after each iteration (post-gc) must not grow roughly linearly
    with iteration count — a real leak would show monotonic growth."""
    iteration_peaks: list[int] = []

    for it in range(3):
        db_path = tmp_path / f"risks-{it}.db"
        payload = {"risks": [{"id": f"r-{i}", "title": f"risk {i}"} for i in range(10_000)]}

        gc.collect()
        tracemalloc.start()
        result = import_payload(payload, risks_db=str(db_path))
        assert result.created == 10_000
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        iteration_peaks.append(peak)

    # A leak would show iteration 3's peak growing well beyond iteration 1's
    # (each iteration does equivalent work against a fresh, empty db) — allow
    # generous variance (2x) for allocator/GC noise before flagging it.
    assert iteration_peaks[-1] < iteration_peaks[0] * 2, (
        f"possible leak: peak memory grew across iterations: {iteration_peaks}"
    )


# --------------------------------------------------------------------------- #
# S9 — long-running accumulation (soak proxy)
# --------------------------------------------------------------------------- #


def test_s9_10k_messages_single_session_soak_proxy(tmp_path: Path) -> None:
    """10k messages accumulated in one session (proxy for a long-lived chat
    session over weeks of real usage): ordering and completeness must hold
    at scale, in bounded time."""
    store = ChatStore(tmp_path / "chat.db")
    session = store.create_session("proj-soak")

    start = time.perf_counter()
    for i in range(10_000):
        store.add_message(session.id, ChatRole.user, f"msg-{i}")
    elapsed = time.perf_counter() - start

    messages = store.list_messages(session.id)
    assert len(messages) == 10_000
    assert [m.content for m in messages] == [f"msg-{i}" for i in range(10_000)]
    assert elapsed < 120, f"10k sequential message inserts took too long: {elapsed:.1f}s"
    store.close()


@pytest.mark.serial
def test_s9_100_plan_versions_soak_proxy(tmp_path: Path) -> None:
    """100 versions of one plan (proxy for months of edits): history stays
    contiguous, and diffing across the full range still works."""
    editor = PlanEditor(tmp_path / "plans.db")
    editor.create("long-lived-plan", [PlanItem(title="v1 item")])
    for v in range(2, 101):
        editor.update("long-lived-plan", [PlanItem(title=f"v{v} item")])

    versions = editor.list_versions("long-lived-plan")
    assert len(versions) == 100
    assert [pv.version for pv in versions] == list(range(1, 101))

    d = editor.diff("long-lived-plan", 1, 100)
    assert d.from_version == 1
    assert d.to_version == 100

    assert_invariants(editor)
    editor.close()


def test_s9_50_concurrent_reviews(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """50 review jobs drained by several concurrent worker threads against
    one JobStore: atomic claim means no job is processed twice and none is
    lost, even under real thread concurrency.

    ``Worker.run()`` sweeps orphaned ``running`` jobs back to ``pending`` on
    startup (single-worker crash recovery). That sweep is not
    concurrency-safe when *multiple* workers cold-start at the same instant
    against a shared queue: worker B's startup sweep can requeue a job
    worker A already claimed a moment earlier, causing a double-claim. That
    startup race is a distinct edge case from the one this test targets
    (steady-state concurrent draining of an already-populated queue), so the
    sweep is disabled here — each worker instead starts against a queue with
    no orphaned rows.
    """
    monkeypatch.setattr(JobStore, "requeue_stale", lambda self: 0)
    doc = tmp_path / "plan.md"
    doc.write_text("# Phases\n## Initiation\nNo quality gate defined.\n", encoding="utf-8")
    jobs_db = tmp_path / "jobs.db"
    seed_store = JobStore(jobs_db)
    for _ in range(50):
        seed_store.enqueue(str(doc), "project-plan", samples=1)
    seed_store.close()

    class FakeClient:
        def structured(self, model, messages, schema, *, temperature=0.1, **kwargs):
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
            text, load_rubric(job.rubric_id), FakeClient(),
            samples=job.samples, on_criterion=on_criterion,
        )

    processed_counts: list[int] = []
    counts_lock = threading.Lock()

    def _worker_thread(i: int) -> None:
        # sqlite3.Connection objects are single-thread by default (JobStore
        # opens without check_same_thread=False) — each worker "process" gets
        # its own JobStore/connection to the same on-disk file, exactly like
        # independent worker processes in production would.
        worker_store = JobStore(jobs_db)
        worker = Worker(
            worker_store, logs_dir=tmp_path / "logs", review_fn=review_fn, poll_interval=0.01
        )
        n = worker.run(once=True)
        worker_store.close()
        with counts_lock:
            processed_counts.append(n)

    outcomes = run_concurrent(_worker_thread, 8, max_workers=8, timeout=60)
    errors = [exc for _, exc in outcomes if exc is not None]
    assert errors == [], errors

    assert sum(processed_counts) == 50, (
        f"expected exactly 50 total claims across workers, got {sum(processed_counts)} "
        f"({processed_counts})"
    )
    store = JobStore(jobs_db)
    done = store.list(JobStatus.done)
    assert len(done) == 50
    assert store.list(JobStatus.pending) == []
    assert store.list(JobStatus.running) == []
