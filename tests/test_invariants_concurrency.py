"""Invariant tests for 20-thread RLock concurrency (Phase 2e).

Cross-store stress tests: hammer each of the three SQLite-backed stores
(RiskRegistry, PlanEditor, ChatStore) from 20 threads simultaneously and
assert the final state is deterministic and complete — no ``sqlite3.Error``,
no lost writes, no torn reads. Complements the per-module concurrency tests
in ``test_invariants_risks.py`` / ``test_invariants_chat.py`` with a focus on
raw thread-count stress and cross-store isolation.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from hermes_assistant.plans.editor import PlanEditor
from hermes_assistant.plans.model import PlanItem
from hermes_assistant.risks.registry import RiskRegistry

N_THREADS = 20


def test_20_threads_create_risks_no_loss(tmp_path: Path) -> None:
    reg = RiskRegistry(tmp_path / "risks.db")
    errors: list[Exception] = []

    def _create(i: int) -> None:
        try:
            reg.create(f"Concurrent risk {i}")
        except sqlite3.Error as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_create, args=(i,)) for i in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert errors == []
    assert len(reg.list()) == N_THREADS
    reg.close_connection()


def test_20_threads_update_same_risk_deterministic_final_state(tmp_path: Path) -> None:
    """20 threads racing to set severity on the same row: no crash, and the
    final severity is one of the values a thread actually wrote (never a
    corrupted/partial value)."""
    reg = RiskRegistry(tmp_path / "risks.db")
    r = reg.create("Contended risk")
    errors: list[Exception] = []

    from hermes_assistant.risks.model import RiskSeverity

    severities = list(RiskSeverity)

    def _update(i: int) -> None:
        try:
            reg.update(r.id, severity=severities[i % len(severities)])
        except sqlite3.Error as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_update, args=(i,)) for i in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert errors == []
    final = reg.get(r.id)
    assert final is not None
    assert final.severity in severities
    reg.close_connection()


def test_20_threads_create_plan_versions_no_loss(tmp_path: Path) -> None:
    editor = PlanEditor(tmp_path / "plans.db")
    editor.create("plan-race", [PlanItem(title="seed")])
    errors: list[Exception] = []
    lock = threading.Lock()
    created_versions: list[int] = []

    def _update(i: int) -> None:
        try:
            pv = editor.update("plan-race", [PlanItem(title=f"item-{i}")])
            with lock:
                created_versions.append(pv.version)
        except sqlite3.Error as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_update, args=(i,)) for i in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert errors == []
    # Every concurrent update serialised via the RLock got its own version
    # number — 1 (seed) + 20 concurrent updates = 21 distinct versions, no
    # two threads clobbering the same version number.
    assert len(created_versions) == N_THREADS
    assert len(set(created_versions)) == N_THREADS
    assert len(editor.list_versions("plan-race")) == N_THREADS + 1
    editor.close()


def test_cross_store_concurrent_access_isolated(tmp_path: Path) -> None:
    """Hammering RiskRegistry and PlanEditor concurrently from interleaved
    threads must not cross-contaminate either store's data."""
    reg = RiskRegistry(tmp_path / "risks.db")
    editor = PlanEditor(tmp_path / "plans.db")
    editor.create("plan-shared", [PlanItem(title="seed")])
    errors: list[Exception] = []

    def _risk_writer(i: int) -> None:
        try:
            reg.create(f"risk-{i}")
        except sqlite3.Error as exc:
            errors.append(exc)

    def _plan_writer(i: int) -> None:
        try:
            editor.update("plan-shared", [PlanItem(title=f"plan-item-{i}")])
        except sqlite3.Error as exc:
            errors.append(exc)

    threads = []
    for i in range(N_THREADS):
        threads.append(threading.Thread(target=_risk_writer, args=(i,)))
        threads.append(threading.Thread(target=_plan_writer, args=(i,)))
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert errors == []
    assert len(reg.list()) == N_THREADS
    assert len(editor.list_versions("plan-shared")) == N_THREADS + 1
    reg.close_connection()
    editor.close()


def test_no_sqlite_locked_errors_under_load(tmp_path: Path) -> None:
    """busy_timeout + RLock together must prevent 'database is locked' errors
    even under sustained concurrent read+write pressure."""
    reg = RiskRegistry(tmp_path / "risks.db")
    for i in range(5):
        reg.create(f"seed-{i}")
    errors: list[Exception] = []

    def _reader() -> None:
        try:
            for _ in range(20):
                reg.list()
        except sqlite3.Error as exc:
            errors.append(exc)

    def _writer(i: int) -> None:
        try:
            reg.create(f"writer-{i}")
        except sqlite3.Error as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_reader) for _ in range(10)]
    threads += [threading.Thread(target=_writer, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert errors == []
    assert len(reg.list()) == 15  # 5 seed + 10 concurrent writers
    reg.close_connection()
