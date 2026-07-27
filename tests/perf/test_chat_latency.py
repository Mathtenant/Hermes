"""Performance tests for chat orchestration (Phase 5.7).

These measure the framework overhead of a chat turn and of SQLite persistence,
excluding LLM inference (which is mocked). Thresholds are generous so the tests
are stable on modest hardware while still catching gross regressions.
"""

from __future__ import annotations

import time

from hermes_assistant.chat.model import IntentClassification
from hermes_assistant.chat.service import ChatService
from hermes_assistant.chat.store import ChatStore


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
