"""P1 edge-case simulations: corruption recovery, partial failure, slow LLM,
boundary conditions, and replay idempotency (S4, S5, S6, S8, S10).

Nothing here touches a live Ollama service — S6 monkeypatches
``requests.post`` at the transport layer used by ``OllamaClient``.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from hermes_assistant.plans.editor import PlanEditor
from hermes_assistant.risks.registry import RiskRegistry
from hermes_assistant.tasks.store import TaskStore
from hermes_assistant.webapp.import_json import (
    _MAX_ITEMS_PER_TYPE,
    import_payload,
    validate_import_payload,
)

from ..conftest import make_response
from .faults import (
    InjectedFailureError,
    corrupt_wal,
    flaky,
    plant_stale_lock,
    run_concurrent,
    truncate_file,
)
from .snapshots import assert_invariants


def _paths(tmp_path: Path) -> dict[str, str]:
    return {
        "risks_db": str(tmp_path / "risks.db"),
        "plans_db": str(tmp_path / "plans.db"),
        "tasks_db": str(tmp_path / "tasks.db"),
        "projects_root": str(tmp_path / "projects"),
    }


# --------------------------------------------------------------------------- #
# S4 — corruption recovery (3 variants)
# --------------------------------------------------------------------------- #


def test_s4_wal_corruption_recovers_without_crash(tmp_path: Path) -> None:
    """A corrupted ``-wal`` sidecar must degrade safely — either SQLite's
    per-frame checksums stop replay cleanly (some/all uncheckpointed rows
    lost, but whatever survives is structurally intact), or the corruption
    is severe enough to leave a genuinely unreadable database image, in
    which case it must surface as a clean, typed ``sqlite3.DatabaseError`` —
    never a hang, a silent wrong answer, or an unhandled crash of another
    kind. Both outcomes are legitimate for the same fault depending on
    exactly which bytes a real crash happens to corrupt.
    """
    db_path = tmp_path / "risks.db"
    writer = RiskRegistry(db_path)
    for i in range(5):
        writer.create(f"pre-crash risk {i}")

    corrupted = corrupt_wal(db_path)
    assert corrupted, "expected a non-empty -wal sidecar to corrupt"

    # A second, independent connection stands in for the process that
    # restarts after a crash and must open the on-disk state as-is.
    try:
        reader = RiskRegistry(db_path)
        risks = reader.list()
    except sqlite3.DatabaseError as exc:
        # Severe corruption: acceptable as long as it's this specific,
        # typed, clearly-diagnosable error — not a hang or a bare crash.
        assert "malformed" in str(exc) or "corrupt" in str(exc)
    else:
        assert len(risks) <= 5
        assert_invariants(reader)
        reader.close_connection()

    writer.close_connection()


def test_s4_truncated_db_file_raises_clear_error(tmp_path: Path) -> None:
    """A truncated main db file (disk full / killed mid-checkpoint) must
    raise a clear ``sqlite3.DatabaseError``, never silently return wrong data."""
    db_path = tmp_path / "risks.db"
    reg = RiskRegistry(db_path)
    for i in range(50):
        reg.create(f"risk-{i}")
    # Force a checkpoint so the main file actually holds the committed rows
    # before we truncate it.
    reg._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    reg.close_connection()

    original_size = truncate_file(db_path, keep_bytes=Path(db_path).stat().st_size // 2)
    assert original_size > 0

    with pytest.raises(sqlite3.DatabaseError):
        reader = RiskRegistry(db_path)
        reader.list()


def test_s4_stale_shm_lock_file_recovers(tmp_path: Path) -> None:
    """A stale/corrupt ``-shm`` file (crash artefact) must be transparently
    rebuilt by SQLite; committed data must remain fully readable."""
    db_path = tmp_path / "risks.db"
    writer = RiskRegistry(db_path)
    for i in range(5):
        writer.create(f"risk-{i}")

    plant_stale_lock(db_path)

    reader = RiskRegistry(db_path)
    risks = reader.list()
    assert len(risks) == 5
    assert_invariants(reader)
    reader.close_connection()
    writer.close_connection()


# --------------------------------------------------------------------------- #
# S5 — cross-entity partial failure
# --------------------------------------------------------------------------- #


def test_s5_risks_commit_plans_fail_mid_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plans-batch failure must not roll back an already-committed risks batch.

    ``import_json``'s module docstring documents that risks commit in a
    single transaction, while plans/pendenzen are written via "sequential
    public-API calls" (no surrounding transaction). We inject a failure into
    the second plan's ``PlanEditor.create`` call to force a mid-batch error
    and verify: (1) risks — an independent, already-committed entity-type
    batch — are unaffected; (2) the plan that committed *before* the failure
    (p1) stays committed, while the failing plan (p2) and the never-attempted
    plan (p3) are absent — the documented, non-atomic behaviour for plans.
    """
    orig_create = PlanEditor.create
    monkeypatch.setattr(PlanEditor, "create", flaky(orig_create, fail_on_call=2))

    payload = {
        "risks": [{"title": "R1"}, {"title": "R2"}],
        "plans": [
            {"plan_id": "p1", "items": [{"title": "A"}]},
            {"plan_id": "p2", "items": [{"title": "B"}]},
            {"plan_id": "p3", "items": [{"title": "C"}]},
        ],
    }
    paths = _paths(tmp_path)

    with pytest.raises(InjectedFailureError):
        import_payload(
            payload, risks_db=paths["risks_db"], plans_db=paths["plans_db"]
        )

    reg = RiskRegistry(paths["risks_db"])
    assert len(reg.list()) == 2
    reg.close_connection()

    editor = PlanEditor(paths["plans_db"])
    assert editor.get("p1") is not None
    assert editor.get("p2") is None
    assert editor.get("p3") is None
    editor.close()


# --------------------------------------------------------------------------- #
# S6 — slow / hung Ollama (3 variants)
# --------------------------------------------------------------------------- #


def test_s6_high_latency_ollama_completes_and_is_traced(client, mock_post, tracer) -> None:
    """A slow-but-eventually-responding Ollama call completes and its
    measured latency is faithfully recorded in the trace log."""
    delay_s = 0.15

    def _slow(*args: object, **kwargs: object):
        time.sleep(delay_s)
        return make_response({"message": {"content": "ok"}})

    mock_post.side_effect = _slow

    result = client.chat("qwen3:4b", [{"role": "user", "content": "hi"}])
    assert result == "ok"

    records = tracer.read_all()
    assert len(records) == 1
    assert records[0].success is True
    assert records[0].latency_ms >= delay_s * 1000 * 0.8  # allow scheduling jitter


def test_s6_hung_ollama_raises_timeout_and_traces_failure(client, mock_post, tracer) -> None:
    """A hung Ollama connection (request never returns within budget) must
    surface as a typed ``OllamaTimeoutError``, not hang the caller forever,
    and the failure must be traced."""
    import requests

    from hermes_assistant.llm.client import OllamaTimeoutError

    mock_post.side_effect = requests.exceptions.ReadTimeout("simulated hang")

    with pytest.raises(OllamaTimeoutError):
        client.chat("qwen3:4b", [{"role": "user", "content": "hi"}])

    records = tracer.read_all()
    assert len(records) == 1
    assert records[0].success is False
    # The client wraps ReadTimeout into a typed, URL-scoped message (see
    # OllamaClient._post) rather than leaking the raw transport exception.
    assert "Timed out" in (records[0].error or "")


def test_s6_thread_exhaustion_many_concurrent_calls_no_deadlock(client, mock_post) -> None:
    """20 concurrent ``chat()`` calls against a backend that can genuinely
    only serve 4 requests at a time (simulated thread-pool exhaustion on the
    Ollama side) must all still complete — no deadlock, no starved caller."""
    max_concurrent = 4
    sem = threading.Semaphore(max_concurrent)

    def _handler(*args: object, **kwargs: object):
        acquired = sem.acquire(timeout=5)
        assert acquired, "simulated Ollama backend exhausted: too many concurrent requests"
        try:
            time.sleep(0.02)
            return make_response({"message": {"content": "ok"}})
        finally:
            sem.release()

    mock_post.side_effect = _handler

    def _call(i: int) -> str:
        return client.chat("qwen3:4b", [{"role": "user", "content": f"msg-{i}"}])

    outcomes = run_concurrent(_call, 20, max_workers=20, timeout=30)
    errors = [exc for _, exc in outcomes if exc is not None]
    assert errors == [], errors
    assert all(result == "ok" for result, exc in outcomes if exc is None)


# --------------------------------------------------------------------------- #
# S8 — boundary conditions
# --------------------------------------------------------------------------- #


def test_s8_empty_batch_is_a_harmless_noop(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    result = import_payload({"risks": []}, **paths)
    assert result.ok
    assert result.created == 0
    assert result.updated == 0
    assert result.skipped == 0


def test_s8_single_item_batch(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    result = import_payload({"risks": [{"title": "Solo risk"}]}, **paths)
    assert result.created == 1


def test_s8_title_10k_chars_round_trips_exactly(tmp_path: Path) -> None:
    huge_title = "R" * 10_000
    paths = _paths(tmp_path)
    result = import_payload({"risks": [{"title": huge_title}]}, **paths)
    assert result.created == 1

    reg = RiskRegistry(paths["risks_db"])
    stored = reg.list()
    assert len(stored) == 1
    assert len(stored[0].title) == 10_000
    assert stored[0].title == huge_title
    reg.close_connection()


def test_s8_batch_at_max_items_succeeds(tmp_path: Path) -> None:
    """Exactly ``_MAX_ITEMS_PER_TYPE`` items is the documented limit — must
    still succeed (single-transaction commit keeps this fast)."""
    paths = _paths(tmp_path)
    payload = {
        "risks": [{"id": f"r-{i}", "title": f"risk {i}"} for i in range(_MAX_ITEMS_PER_TYPE)]
    }
    result = import_payload(payload, **paths)
    assert result.created == _MAX_ITEMS_PER_TYPE

    reg = RiskRegistry(paths["risks_db"])
    assert len(reg.list()) == _MAX_ITEMS_PER_TYPE
    reg.close_connection()


def test_s8_batch_over_max_items_rejected(tmp_path: Path) -> None:
    payload = {
        "risks": [
            {"id": f"r-{i}", "title": f"risk {i}"} for i in range(_MAX_ITEMS_PER_TYPE + 1)
        ]
    }
    errors = validate_import_payload(payload)
    assert any("maximum is" in e for e in errors)


def test_s8_zero_duration_milestone_clamped_to_one_working_day(tmp_path: Path) -> None:
    """An ``effort_days=0`` milestone must not collapse to a zero-length (or
    negative) schedule step — ``derive_schedule`` clamps to a 1-working-day
    minimum (see ``_add_working_days``'s ``max(1, round(n))``)."""
    from datetime import date

    from hermes_assistant.hermes.model import Approach, Milestone, Phase, ProjectPlan
    from hermes_assistant.scheduling.derive import _SimpleWeekdayCal, derive_schedule

    plan = ProjectPlan(
        title="t", scenario="t", approach=Approach.traditional,
        phases=[
            Phase(
                id="p1", name="p1",
                milestones=[Milestone(id="m1", name="m1", effort_days=0.0)],
                outcomes=[],
            )
        ],
        roles=[],
    )
    schedule = derive_schedule(
        plan,
        project_id="proj",
        project_label="proj",
        start_date=date(2026, 1, 5),  # a Monday
        calendar=_SimpleWeekdayCal(),
    )
    assert len(schedule.items) == 1
    item = schedule.items[0]
    # Zero effort must not schedule the item on (or before) the start date —
    # it must still consume at least one working day.
    assert item.due > date(2026, 1, 5)


def test_s8_deeply_nested_json_does_not_crash_the_process(tmp_path: Path) -> None:
    """A pathologically deep JSON array (the same ``json.loads`` code path
    ``webapp/server.py``'s import endpoint uses on the raw request body) must
    raise a catchable error, never an unrecoverable process crash."""
    depth = 5000
    pathological = "[" * depth + "]" * depth
    with pytest.raises((RecursionError, ValueError)):
        json.loads(pathological)


# --------------------------------------------------------------------------- #
# S10 — replay idempotency
# --------------------------------------------------------------------------- #


def test_s10_replay_ten_times_converges_no_duplicates(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    payload = {
        "risks": [{"external_ref": "ext-1", "title": "Risk A"}],
        "plans": [{"plan_id": "plan-a", "items": [{"title": "Item"}]}],
        "pendenzen": [{"title": "Task A", "external_ref": "pend-1"}],
    }

    results = [import_payload(payload, **paths) for _ in range(10)]

    first, rest = results[0], results[1:]
    assert first.created == 3 and first.updated == 0
    for r in rest:
        assert r.created == 0, f"unexpected new rows on replay: {r.items}"
        assert r.updated == 3

    reg = RiskRegistry(paths["risks_db"])
    risks = reg.list()
    assert len(risks) == 1
    refs = [r.external_ref for r in risks if r.external_ref]
    assert len(refs) == len(set(refs)) == 1, "duplicate external_ref after replay"
    assert_invariants(reg)
    reg.close_connection()

    editor = PlanEditor(paths["plans_db"])
    assert editor.list_plans() == ["plan-a"]
    assert len(editor.list_versions("plan-a")) == 10  # each import bumps the version
    assert_invariants(editor)
    editor.close()

    store = TaskStore(paths["tasks_db"])
    matches = [n for n in store.tree().get("children", []) if n.get("title") == "Task A"]
    assert len(matches) == 1
    store.close()
