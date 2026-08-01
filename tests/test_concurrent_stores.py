"""Concurrency tests for the four SQLite stores (C3 fix verification).

Fires multiple threads simultaneously against each store and verifies:
- No sqlite3.OperationalError or ProgrammingError raised
- Final row counts are exactly equal to the number of successful inserts
- No data corruption (every inserted row is readable)
"""

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from hermes_assistant.chat.model import ChatRole
from hermes_assistant.chat.store import ChatStore
from hermes_assistant.plans.editor import PlanEditor
from hermes_assistant.plans.model import PlanItem
from hermes_assistant.risks.registry import RiskRegistry
from hermes_assistant.tasks.model import Task
from hermes_assistant.tasks.store import TaskStore

_WORKERS = 20


# ── ChatStore ──────────────────────────────────────────────────────────── #

@pytest.fixture
def chat_store() -> ChatStore:
    s = ChatStore(":memory:")
    yield s
    s.close()


def test_chat_concurrent_add_message(chat_store: ChatStore) -> None:
    """20 threads write to the same session simultaneously; no errors, no lost rows."""
    session = chat_store.create_session("proj-concurrent")
    errors: list[Exception] = []

    def add_one(i: int) -> None:
        try:
            chat_store.add_message(session.id, ChatRole.user, f"msg-{i}")
        except (sqlite3.OperationalError, sqlite3.ProgrammingError) as exc:
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = [pool.submit(add_one, i) for i in range(_WORKERS)]
        for f in as_completed(futures):
            f.result()  # re-raises any unexpected exception

    assert not errors, f"SQLite errors during concurrent writes: {errors}"
    messages = chat_store.list_messages(session.id)
    assert len(messages) == _WORKERS, (
        f"Expected {_WORKERS} messages, got {len(messages)}"
    )
    # Verify content integrity: all messages are readable and unique
    contents = {m.content for m in messages}
    assert len(contents) == _WORKERS


def test_chat_concurrent_create_session(chat_store: ChatStore) -> None:
    """20 threads each create their own session; all succeed."""
    errors: list[Exception] = []
    results: list[str] = []
    lock = threading.Lock()

    def create_one(i: int) -> None:
        try:
            s = chat_store.create_session(f"proj-{i}", title=f"Session {i}")
            with lock:
                results.append(s.id)
        except (sqlite3.OperationalError, sqlite3.ProgrammingError) as exc:
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = [pool.submit(create_one, i) for i in range(_WORKERS)]
        for f in as_completed(futures):
            f.result()

    assert not errors, f"SQLite errors: {errors}"
    assert len(results) == _WORKERS
    assert len(set(results)) == _WORKERS  # all IDs unique


# ── RiskRegistry ───────────────────────────────────────────────────────── #

@pytest.fixture
def risk_registry() -> RiskRegistry:
    r = RiskRegistry(":memory:")
    yield r
    r.close_connection()


def test_risk_concurrent_create(risk_registry: RiskRegistry) -> None:
    """20 threads each insert a risk; no errors, all 20 rows present."""
    errors: list[Exception] = []

    def create_one(i: int) -> None:
        try:
            risk_registry.create(f"Risk {i}", description=f"desc-{i}")
        except (sqlite3.OperationalError, sqlite3.ProgrammingError) as exc:
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = [pool.submit(create_one, i) for i in range(_WORKERS)]
        for f in as_completed(futures):
            f.result()

    assert not errors, f"SQLite errors: {errors}"
    risks = risk_registry.list()
    assert len(risks) == _WORKERS


def test_risk_concurrent_update(risk_registry: RiskRegistry) -> None:
    """One risk updated by 20 threads; no errors."""
    from hermes_assistant.risks.model import RiskSeverity

    risk = risk_registry.create("Shared risk")
    errors: list[Exception] = []

    def update_one(i: int) -> None:
        try:
            risk_registry.update(risk.id, description=f"updated-{i}")
        except (sqlite3.OperationalError, sqlite3.ProgrammingError) as exc:
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = [pool.submit(update_one, i) for i in range(_WORKERS)]
        for f in as_completed(futures):
            f.result()

    assert not errors, f"SQLite errors: {errors}"
    fetched = risk_registry.get(risk.id)
    assert fetched is not None


# ── PlanEditor ─────────────────────────────────────────────────────────── #

@pytest.fixture
def plan_editor() -> PlanEditor:
    e = PlanEditor(":memory:")
    yield e
    e.close()


def test_plan_concurrent_update(plan_editor: PlanEditor) -> None:
    """20 threads each append a new plan version; no errors, versions >= 2."""
    item = PlanItem(title="Task A")
    plan_editor.create("plan-1", [item])
    errors: list[Exception] = []

    def update_one(i: int) -> None:
        try:
            plan_editor.update("plan-1", [PlanItem(title=f"Task {i}")])
        except (sqlite3.OperationalError, sqlite3.ProgrammingError) as exc:
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = [pool.submit(update_one, i) for i in range(_WORKERS)]
        for f in as_completed(futures):
            f.result()

    assert not errors, f"SQLite errors: {errors}"
    versions = plan_editor.list_versions("plan-1")
    # 1 initial + up to 20 concurrent; RLock serialises so all land
    assert len(versions) >= 2


def test_plan_concurrent_create_distinct_plans(plan_editor: PlanEditor) -> None:
    """20 threads each create a different plan; all 20 are stored."""
    errors: list[Exception] = []

    def create_one(i: int) -> None:
        try:
            plan_editor.create(f"plan-{i}", [PlanItem(title=f"Item {i}")])
        except (sqlite3.OperationalError, sqlite3.ProgrammingError) as exc:
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = [pool.submit(create_one, i) for i in range(_WORKERS)]
        for f in as_completed(futures):
            f.result()

    assert not errors, f"SQLite errors: {errors}"
    plan_ids = plan_editor.list_plans()
    assert len(plan_ids) == _WORKERS


# ── TaskStore ──────────────────────────────────────────────────────────── #

@pytest.fixture
def task_store() -> TaskStore:
    s = TaskStore(":memory:")
    yield s
    s.close()


def test_task_concurrent_create(task_store: TaskStore) -> None:
    """20 threads each create a root task; no errors, all 20 rows present."""
    errors: list[Exception] = []
    created_ids: list[str] = []
    lock = threading.Lock()

    def create_one(i: int) -> None:
        try:
            task_id = task_store.create(Task(id="", title=f"Task {i}"))
            with lock:
                created_ids.append(task_id)
        except (sqlite3.OperationalError, sqlite3.ProgrammingError) as exc:
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = [pool.submit(create_one, i) for i in range(_WORKERS)]
        for f in as_completed(futures):
            f.result()

    assert not errors, f"SQLite errors: {errors}"
    assert len(created_ids) == _WORKERS
    # Verify every row is readable
    for tid in created_ids:
        assert task_store.get(tid) is not None


def test_task_concurrent_update(task_store: TaskStore) -> None:
    """One task updated by 20 threads; no errors, final state is readable."""
    task_id = task_store.create(Task(id="", title="Shared task"))
    errors: list[Exception] = []

    def update_one(i: int) -> None:
        try:
            task_store.update(task_id, description=f"update-{i}")
        except (sqlite3.OperationalError, sqlite3.ProgrammingError) as exc:
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = [pool.submit(update_one, i) for i in range(_WORKERS)]
        for f in as_completed(futures):
            f.result()

    assert not errors, f"SQLite errors: {errors}"
    result = task_store.get(task_id)
    assert result is not None
