"""Unit tests for ChatService orchestration & ResponseFormatter (Phase 5.4)."""

from __future__ import annotations

from hermes_assistant.chat.model import ChatRole, IntentClassification
from hermes_assistant.chat.service import ChatService, ResponseFormatter
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
