"""Performance tests for chat orchestration (Phase 5.7).

These measure the framework overhead of a chat turn and of SQLite persistence,
excluding LLM inference (which is mocked). Thresholds are generous so the tests
are stable on modest hardware while still catching gross regressions.
"""

from __future__ import annotations

import concurrent.futures
import json
import time

from hermes_assistant.chat.model import IntentClassification
from hermes_assistant.chat.service import ChatService
from hermes_assistant.chat.store import ChatStore
from hermes_assistant.webapp.server import _validate_safe_json


class _FastRouter:
    def classify(self, message, context):  # noqa: ANN001
        return IntentClassification(intent="smalltalk", params={}, confidence=0.9)


class _FastExecutor:
    def execute(self, action_type, params, context):  # noqa: ANN001
        return {"action": "answer", "answer": "OK"}


def test_chat_orchestration_overhead():
    """End-to-end orchestration latency (excluding LLM) stays small."""
    store = ChatStore(":memory:")
    service = ChatService(store, _FastRouter(), _FastExecutor(), None)

    times = []
    for i in range(10):
        start = time.time()
        service.handle_turn(f"Message {i}", "proj1")
        times.append(time.time() - start)

    avg_time = sum(times) / len(times)
    assert avg_time < 0.1, f"Orchestration took {avg_time:.3f}s (target < 0.1s)"
    assert max(times) < 0.2, f"Max latency {max(times):.3f}s (target < 0.2s)"


def test_database_query_performance():
    """SQLite writes and list queries are fast."""
    store = ChatStore(":memory:")

    start = time.time()
    for session_num in range(10):
        session = store.create_session(f"proj{session_num % 3}")
        for msg_num in range(10):
            role = "user" if msg_num % 2 == 0 else "assistant"
            store.add_message(session.id, role, f"Message {msg_num}")
    create_time = time.time() - start
    assert create_time < 0.5, f"Created 100 messages in {create_time:.3f}s"

    start = time.time()
    store.list_sessions()
    list_time = time.time() - start
    assert list_time < 0.05, f"Listed sessions in {list_time:.3f}s"


def test_concurrent_message_handling_no_deadlock() -> None:
    """20 parallel handle_turn calls on the same session must all succeed."""
    store = ChatStore(":memory:")
    service = ChatService(store, _FastRouter(), _FastExecutor(), None)

    # Pre-create the shared session before spawning threads.
    session = store.create_session("proj-concurrent")
    session_id = session.id

    errors: list[Exception] = []
    results: list[object] = []

    def one_turn(i: int) -> None:
        try:
            turn = service.handle_turn(f"Message {i}", "proj-concurrent", session_id)
            results.append(turn)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        futures = [pool.submit(one_turn, i) for i in range(20)]
        concurrent.futures.wait(futures)

    assert not errors, f"Errors in concurrent turns: {errors!r}"
    assert len(results) == 20, f"Expected 20 turns, got {len(results)}"
    # Each turn persists 1 user + 1 assistant message → 40 total.
    msgs = store.list_messages(session_id)
    assert len(msgs) == 40, f"Expected 40 messages (20 × 2), got {len(msgs)}"


def test_guard_validation_overhead() -> None:
    """_validate_safe_json runs in under 10 ms for a typical response payload."""
    payload = json.dumps({
        "content": "Hello! What are you working on?",
        "intent": "smalltalk",
        "session_id": "abc123",
        "risks": [],
        "suggestions": ["Create a risk", "List tasks"],
    })

    # Warm-up: first call may trigger module-level regex compilation.
    _validate_safe_json(payload)

    times_ms = []
    for _ in range(100):
        start = time.perf_counter()
        _validate_safe_json(payload)
        times_ms.append((time.perf_counter() - start) * 1000)

    avg_ms = sum(times_ms) / len(times_ms)
    assert avg_ms < 10.0, (
        f"Guard validation averaged {avg_ms:.3f} ms (target < 10 ms)"
    )
