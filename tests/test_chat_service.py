"""Unit tests for ChatService orchestration & ResponseFormatter (Phase 5.4)."""

from __future__ import annotations

import logging

import pytest

from hermes_assistant.chat.model import ChatRole, IntentClassification
from hermes_assistant.chat.service import ChatService, ConfidentialityGuardError, ResponseFormatter
from hermes_assistant.chat.store import ChatStore


class FakeRouter:
    def classify(self, message, context):  # noqa: ANN001
        if "create" in message.lower() and "task" in message.lower():
            return IntentClassification(
                intent="create_task", params={"title": "Test Task"}, confidence=0.9
            )
        return IntentClassification(intent="answer_question", params={}, confidence=0.5)


class FakeExecutor:
    def execute(self, action_type, params, context):  # noqa: ANN001
        if action_type == "create_task":
            return {"action": "created", "task_id": "t1", "title": params.get("title")}
        return {"action": "answer", "answer": "OK"}


class FakeLLMClient:
    pass


def _service(store: ChatStore) -> ChatService:
    return ChatService(store, FakeRouter(), FakeExecutor(), FakeLLMClient())


def test_service_handle_turn_create_task():
    turn = _service(ChatStore(":memory:")).handle_turn(
        "Create a task called testing", "proj1"
    )
    assert turn.session_id
    assert turn.message.role == ChatRole.assistant
    assert turn.action is not None
    assert turn.action.action_type == "create_task"


def test_service_persist_messages():
    store = ChatStore(":memory:")
    turn = _service(store).handle_turn("Hello", "proj1")
    messages = store.list_messages(turn.session_id)
    assert len(messages) == 2
    assert messages[0].role == ChatRole.user
    assert messages[1].role == ChatRole.assistant


def test_service_session_created():
    store = ChatStore(":memory:")
    turn = _service(store).handle_turn("Test", "proj1")
    session = store.get_session(turn.session_id)
    assert session is not None
    assert session.project_id == "proj1"


def test_service_reuse_session():
    store = ChatStore(":memory:")
    service = _service(store)
    turn1 = service.handle_turn("First message", "proj1")
    turn2 = service.handle_turn("Second message", "proj1", session_id=turn1.session_id)
    assert turn2.session_id == turn1.session_id
    assert len(store.list_messages(turn1.session_id)) == 4


def test_service_low_confidence_fallback():
    class LowConfidenceRouter:
        def classify(self, message, context):  # noqa: ANN001
            return IntentClassification(intent="create_task", params={}, confidence=0.5)

    store = ChatStore(":memory:")
    service = ChatService(store, LowConfidenceRouter(), FakeExecutor(), FakeLLMClient())
    turn = service.handle_turn("Something ambiguous", "proj1")
    assert turn.message.content


def test_service_no_action_on_smalltalk():
    class SmallTalkRouter:
        def classify(self, message, context):  # noqa: ANN001
            return IntentClassification(intent="smalltalk", params={}, confidence=0.9)

    store = ChatStore(":memory:")
    service = ChatService(store, SmallTalkRouter(), FakeExecutor(), FakeLLMClient())
    turn = service.handle_turn("Hello!", "proj1")
    assert turn.action is None


def test_formatter_create_task():
    result = {"action": "created", "task_id": "t1", "title": "Deploy", "priority": "high"}
    text = ResponseFormatter.format_result(result, "create_task")
    assert "Deploy" in text
    assert "created" in text.lower()


def test_formatter_list_risks():
    result = {"action": "list", "count": 5, "risks": [{"title": "Risk1"}]}
    text = ResponseFormatter.format_result(result, "list_risks")
    assert "5" in text
    assert "risks" in text.lower()


def test_formatter_error():
    result = {"error": "Something went wrong"}
    text = ResponseFormatter.format_result(result, "create_task")
    assert "error" in text.lower()


def test_service_suggestions():
    store = ChatStore(":memory:")
    turn = _service(store).handle_turn("Show risks", "proj1")
    assert isinstance(turn.suggestions, list)


# --------------------------------------------------------------------------- #
# Q1 — conversational intents (smalltalk / capability / meta / unknown)
# --------------------------------------------------------------------------- #


def test_formatter_smalltalk_greeting_en():
    text = ResponseFormatter.format_result({}, "smalltalk", "Hello there")
    assert "Hello" in text


def test_formatter_smalltalk_greeting_de():
    text = ResponseFormatter.format_result({}, "smalltalk", "Hallo, grüße dich")
    assert "Hallo" in text


def test_formatter_smalltalk_thanks():
    text = ResponseFormatter.format_result({}, "smalltalk", "Thanks a lot")
    assert "welcome" in text.lower()


def test_formatter_capability_lists_examples():
    text = ResponseFormatter.format_result({}, "capability", "What can you do?")
    assert "risk" in text.lower()
    assert "task" in text.lower()


def test_formatter_meta_model():
    text = ResponseFormatter.format_result({}, "meta", "What model are you?")
    assert "qwen" in text.lower()


def test_formatter_meta_local():
    text = ResponseFormatter.format_result({}, "meta", "Do you run locally?")
    assert "local" in text.lower()


def test_formatter_unknown_has_suggestions():
    text = ResponseFormatter.format_result({}, "unknown", "flibber the wozzle")
    assert "[suggestions]" not in text
    assert "risk" in text.lower()


def test_service_capability_no_action():
    class CapabilityRouter:
        def classify(self, message, context):  # noqa: ANN001
            return IntentClassification(intent="capability", params={}, confidence=0.95)

    store = ChatStore(":memory:")
    service = ChatService(store, CapabilityRouter(), FakeExecutor(), FakeLLMClient())
    turn = service.handle_turn("What can you do?", "proj1")
    assert turn.action is None
    assert "risk" in turn.message.content.lower()


def test_service_meta_no_action():
    class MetaRouter:
        def classify(self, message, context):  # noqa: ANN001
            return IntentClassification(intent="meta", params={}, confidence=0.9)

    store = ChatStore(":memory:")
    service = ChatService(store, MetaRouter(), FakeExecutor(), FakeLLMClient())
    turn = service.handle_turn("What model are you?", "proj1")
    assert turn.action is None
    assert "qwen" in turn.message.content.lower()


def test_service_greeting_not_rephrase_fallback():
    class SmallTalkRouter:
        def classify(self, message, context):  # noqa: ANN001
            return IntentClassification(intent="smalltalk", params={}, confidence=0.99)

    store = ChatStore(":memory:")
    service = ChatService(store, SmallTalkRouter(), FakeExecutor(), FakeLLMClient())
    turn = service.handle_turn("Hello", "proj1")
    assert "rephrase" not in turn.message.content.lower()
    assert "Hello" in turn.message.content


# --------------------------------------------------------------------------- #
# H1 — confidentiality guard runs BEFORE persistence
# --------------------------------------------------------------------------- #


class _HighConfidenceRouter:
    """Always classifies with high confidence so the executor is called."""

    def classify(self, message, context):  # noqa: ANN001
        return IntentClassification(intent="answer_question", params={}, confidence=0.9)


class _PiiLeakExecutor:
    """Simulates an LLM result that contains PII (email address)."""

    def execute(self, action_type, params, context):  # noqa: ANN001
        return {"action": "answer", "answer": "Contact alice@example.com for details."}


def test_guard_blocks_before_persist() -> None:
    """H1: guard fires BEFORE persistence; no assistant row written on violation."""
    store = ChatStore(":memory:")
    service = ChatService(store, _HighConfidenceRouter(), _PiiLeakExecutor(), FakeLLMClient())

    with pytest.raises(ConfidentialityGuardError):
        service.handle_turn("Show me contact info", "proj1")

    # Session was created and the user message was persisted, but the
    # assistant response must NOT have been written to chat_messages.
    sessions = store.list_sessions("proj1")
    assert len(sessions) == 1, "session should still exist"
    messages = store.list_messages(sessions[0].id)
    assert len(messages) == 1, "only the user message should be persisted"
    assert messages[0].role == ChatRole.user


def test_guard_logs_violation(caplog: pytest.LogCaptureFixture) -> None:
    """H1+H2: violation details are written to the server log, not the exception."""
    store = ChatStore(":memory:")
    service = ChatService(store, _HighConfidenceRouter(), _PiiLeakExecutor(), FakeLLMClient())

    with caplog.at_level(logging.WARNING, logger="hermes_assistant.chat.service"):
        with pytest.raises(ConfidentialityGuardError) as exc_info:
            service.handle_turn("Show me contact info", "proj1")

    # The exception carries only a generic message — no violation details.
    assert "alice" not in str(exc_info.value)
    assert "example.com" not in str(exc_info.value)

    # The real detail must appear in the server-side log.
    assert "Confidentiality guard blocked" in caplog.text
    assert "alice@example.com" in caplog.text or "Email address" in caplog.text
