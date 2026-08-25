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
    def chat_stream(self, model, messages, **kwargs):  # noqa: ANN001
        yield "Hello"
        yield " world"


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
    # Generic errors (no UNIQUE/not-found keyword) produce the safe fallback.
    result = {"error": "Something went wrong"}
    text = ResponseFormatter.format_result(result, "create_task")
    assert "could not be completed" in text.lower()


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
    """The meta reply names whichever model is active, not a hard-coded one."""
    text = ResponseFormatter.format_result(
        {}, "meta", "What model are you?", "qwen3:4b"
    )
    assert "qwen3:4b" in text

    # Swapping the model must change the answer — otherwise the reply would
    # keep claiming a model the assistant is no longer running.
    swapped = ResponseFormatter.format_result(
        {}, "meta", "What model are you?", "llama3.1:8b"
    )
    assert "llama3.1:8b" in swapped
    assert "qwen" not in swapped.lower()


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
        model = "qwen3:4b"

        def classify(self, message, context):  # noqa: ANN001
            return IntentClassification(intent="meta", params={}, confidence=0.9)

    store = ChatStore(":memory:")
    service = ChatService(store, MetaRouter(), FakeExecutor(), FakeLLMClient())
    turn = service.handle_turn("What model are you?", "proj1")
    assert turn.action is None
    assert "qwen3:4b" in turn.message.content


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


# --------------------------------------------------------------------------- #
# H1 — user-authored PII is exempt from the confidentiality guard
# --------------------------------------------------------------------------- #


def test_guard_exempts_user_authored_email() -> None:
    """H1: a user-role message containing an email must NOT be flagged.

    This is the unit-level root-cause check behind the GET-session 500: the
    guard's value scan (email/path) must skip user-authored message content."""
    from hermes_assistant.webapp.server import (
        _redact_user_authored,
        _validate_safe_json,
    )
    import json as _json

    payload = {
        "session": {"id": "s1", "project_id": "p1"},
        "messages": [
            {"role": "user", "content": "contact me at john@example.com"},
            {"role": "assistant", "content": "Noted."},
        ],
    }
    violations = _validate_safe_json(
        _json.dumps(payload),
        _json.dumps(_redact_user_authored(payload)),
    )
    assert violations == []


def test_guard_still_flags_assistant_email() -> None:
    """H1: the exemption is scoped to user content — an assistant message that
    leaks an email is still blocked."""
    from hermes_assistant.webapp.server import (
        _redact_user_authored,
        _validate_safe_json,
    )
    import json as _json

    payload = {
        "messages": [
            {"role": "user", "content": "who do I contact?"},
            {"role": "assistant", "content": "Email leak@internal.example.com."},
        ],
    }
    violations = _validate_safe_json(
        _json.dumps(payload),
        _json.dumps(_redact_user_authored(payload)),
    )
    assert any("Email" in v for v in violations)


# --------------------------------------------------------------------------- #
# H3 — safe fallback for unhandled result shapes
# --------------------------------------------------------------------------- #


def test_formatter_h3_unhandled_intent_returns_safe_message():
    """H3: An intent with no formatter branch must NOT expose str(result)."""
    result = {"action": "some_future_action", "data": {"nested": "dict"}}
    text = ResponseFormatter.format_result_existing(result, "future_intent")
    # Must not leak the raw dict representation.
    assert "some_future_action" not in text
    assert "nested" not in text
    assert "dict" not in text
    assert "issue processing" in text


def test_formatter_h3_logs_warning(caplog: pytest.LogCaptureFixture):
    """H3: Unhandled result triggers a server-side warning log."""
    result = {"action": "unrecognised", "internal_field": "internal value"}
    with caplog.at_level(logging.WARNING, logger="hermes_assistant.chat.service"):
        ResponseFormatter.format_result_existing(result, "mystery_intent")
    assert "Unhandled result format" in caplog.text
    assert "mystery_intent" in caplog.text


# --------------------------------------------------------------------------- #
# H4 — executor error normalisation
# --------------------------------------------------------------------------- #


def test_formatter_h4_unique_constraint_message():
    """H4: UNIQUE constraint failure produces a user-friendly duplicate message."""
    result = {"error": "UNIQUE constraint failed: risks.id"}
    text = ResponseFormatter.format_result_existing(result, "create_risk")
    assert "already exists" in text.lower()
    assert "UNIQUE" not in text
    assert "risks.id" not in text


def test_formatter_h4_not_found_message():
    """H4: 'not found' errors produce a user-friendly not-found message."""
    result = {"error": "Risk with id 'xyz' not found"}
    text = ResponseFormatter.format_result_existing(result, "show_risk")
    assert "not found" in text.lower()
    assert "xyz" not in text


def test_formatter_h4_generic_error_message():
    """H4: Other internal errors (DB, type errors) produce the safe fallback."""
    result = {"error": "'NoneType' object is not subscriptable"}
    text = ResponseFormatter.format_result_existing(result, "create_risk")
    assert "could not be completed" in text.lower()
    assert "NoneType" not in text
    assert "subscriptable" not in text


def test_formatter_h4_logs_real_error(caplog: pytest.LogCaptureFixture):
    """H4: The original internal error is written to the server log."""
    internal_error = "UNIQUE constraint failed: risks.id"
    result = {"error": internal_error}
    with caplog.at_level(logging.WARNING, logger="hermes_assistant.chat.service"):
        ResponseFormatter.format_result_existing(result, "create_risk")
    assert internal_error in caplog.text


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


# --------------------------------------------------------------------------- #
# M6 — improved language detection (keyword heuristics, not umlaut-only)
# --------------------------------------------------------------------------- #


def test_detect_language_german_without_umlauts():
    """M6: German common words trigger 'de' even when no umlaut is present."""
    assert ResponseFormatter.detect_language("Was kannst du?") == "de"


def test_detect_language_german_with_umlauts_backward_compat():
    """M6: Umlaut fast-path still returns 'de' (backward compatible)."""
    assert ResponseFormatter.detect_language("Grüße aus Berlin") == "de"


def test_detect_language_french_hyphenated():
    """M6: Hyphenated French ('Pouvez-vous?') is detected correctly."""
    assert ResponseFormatter.detect_language("Pouvez-vous?") == "fr"


def test_detect_language_french_sentence():
    """M6: Full French sentence is detected correctly."""
    assert ResponseFormatter.detect_language("Pouvez-vous faire cela?") == "fr"


def test_detect_language_english_default():
    """M6: Unknown or English text falls back to 'en'."""
    assert ResponseFormatter.detect_language("xyzzy frobnicator blorp") == "en"


def test_detect_language_empty_string():
    """M6: Empty input defaults to 'en' (no crash)."""
    assert ResponseFormatter.detect_language("") == "en"


# --------------------------------------------------------------------------- #
# M7 — confidence threshold driven by config (settings.chat_confidence_threshold)
# --------------------------------------------------------------------------- #


def test_service_hydrates_context_from_stores() -> None:
    """M10: ChatContext is hydrated with real risk/task data when the
    risk_registry and task_store are injected into ChatService."""
    from hermes_assistant.risks.model import RiskSeverity
    from hermes_assistant.risks.registry import RiskRegistry
    from hermes_assistant.tasks.model import Task
    from hermes_assistant.tasks.store import TaskStore

    store = ChatStore(":memory:")
    registry = RiskRegistry(":memory:")
    task_store = TaskStore(":memory:")

    registry.create("High Risk", severity=RiskSeverity.high, likelihood=5)
    task_store.create(Task(id="", title="Task 1", status="open"))

    captured: dict = {}

    class CapturingExecutor:
        def execute(self, action_type, params, context):  # noqa: ANN001
            captured["risks"] = context.risks
            captured["open_task_count"] = context.open_task_count
            return {"action": "answer", "answer": "OK"}

    service = ChatService(
        store,
        _HighConfidenceRouter(),
        CapturingExecutor(),
        FakeLLMClient(),
        risk_registry=registry,
        task_store=task_store,
    )

    turn = service.handle_turn("What are my risks?", "p1")
    assert turn.session_id
    assert len(captured["risks"]) == 1
    assert captured["risks"][0]["title"] == "High Risk"
    assert captured["open_task_count"] == 1


def test_service_context_empty_without_stores() -> None:
    """M10: backward compatibility — omitting the stores keeps context empty,
    exactly as before this change."""
    captured: dict = {}

    class CapturingExecutor:
        def execute(self, action_type, params, context):  # noqa: ANN001
            captured["risks"] = context.risks
            captured["open_task_count"] = context.open_task_count
            return {"action": "answer", "answer": "OK"}

    store = ChatStore(":memory:")
    service = ChatService(store, _HighConfidenceRouter(), CapturingExecutor(), FakeLLMClient())
    turn = service.handle_turn("What are my risks?", "p1")
    assert turn.session_id
    assert captured["risks"] == []
    assert captured["open_task_count"] == 0


def test_service_respects_config_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """M7: ChatService uses settings.chat_confidence_threshold, not a hardcoded value."""
    import hermes_assistant.chat.service as svc_module

    class _MockSettings:
        chat_confidence_threshold = 0.95  # Very high — 0.9 router won't reach it

    monkeypatch.setattr(svc_module, "settings", _MockSettings())

    class _NearHighRouter:
        """Returns 0.9 confidence — high under old hardcoded 0.7, low under 0.95."""

        def classify(self, message, context):  # noqa: ANN001
            return IntentClassification(
                intent="create_task", params={"title": "T"}, confidence=0.9
            )

    store = ChatStore(":memory:")
    service = ChatService(store, _NearHighRouter(), FakeExecutor(), FakeLLMClient())
    turn = service.handle_turn("Create task", "proj1")
    # With threshold 0.95, confidence 0.9 is below threshold → no action persisted.
    assert turn.action is None


# --------------------------------------------------------------------------- #
# F3 — stream_turn: SSE streaming generator
# --------------------------------------------------------------------------- #


def _collect_stream(service: ChatService, message: str, project_id: str, session_id=None):  # noqa: ANN001
    """Helper: collect stream_turn() items into (chunks, terminal_dict)."""
    items = list(service.stream_turn(message, project_id, session_id))
    chunks = [i for i in items if isinstance(i, str)]
    terminal = next((i for i in items if isinstance(i, dict)), None)
    return chunks, terminal


def test_stream_turn_yields_text_chunks():
    store = ChatStore(":memory:")
    chunks, _ = _collect_stream(_service(store), "Hello", "proj1")
    assert len(chunks) >= 1
    assembled = "".join(chunks)
    assert len(assembled) > 0


def test_stream_turn_done_event_carries_message_id():
    store = ChatStore(":memory:")
    _, terminal = _collect_stream(_service(store), "Hello", "proj1")
    assert terminal is not None
    assert terminal.get("done") is True
    assert terminal.get("message_id")
    assert terminal.get("session_id")


def test_stream_turn_persists_exactly_one_assistant_message():
    store = ChatStore(":memory:")
    service = _service(store)
    chunks, terminal = _collect_stream(service, "Hello", "proj1")
    messages = store.list_messages(terminal["session_id"])
    # user + assistant = 2 messages; no partial rows
    assert len(messages) == 2
    assert messages[0].role == ChatRole.user
    assert messages[1].role == ChatRole.assistant
    assert messages[1].content == "".join(chunks)


def test_stream_turn_persists_full_assembled_text():
    """The persisted content must equal the joined chunks — never partial."""
    store = ChatStore(":memory:")
    service = _service(store)
    chunks, terminal = _collect_stream(service, "Create a task called X", "proj1")
    messages = store.list_messages(terminal["session_id"])
    assistant_msgs = [m for m in messages if m.role == ChatRole.assistant]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0].content == "".join(chunks)


def test_stream_turn_guard_blocks_pii_response():
    """F3: confidentiality guard on assembled text yields error sentinel, no persist."""
    store = ChatStore(":memory:")
    service = ChatService(
        store, _HighConfidenceRouter(), _PiiLeakExecutor(), FakeLLMClient()
    )
    items = list(service.stream_turn("Show contact info", "proj1"))
    terminal = next((i for i in items if isinstance(i, dict)), None)
    assert terminal is not None
    assert terminal.get("error") is True
    # No assistant message should be persisted after a guard violation.
    sessions = store.list_sessions("proj1")
    messages = store.list_messages(sessions[0].id)
    assistant_msgs = [m for m in messages if m.role == ChatRole.assistant]
    assert len(assistant_msgs) == 0


def test_stream_turn_reuses_existing_session():
    store = ChatStore(":memory:")
    service = _service(store)
    _, done1 = _collect_stream(service, "First", "proj1")
    _, done2 = _collect_stream(service, "Second", "proj1", session_id=done1["session_id"])
    assert done2["session_id"] == done1["session_id"]
    messages = store.list_messages(done1["session_id"])
    assert len(messages) == 4  # user+assistant x2


def test_stream_turn_degradation_fallback():
    """F3: when the router fails (degradation), stream still yields chunks and done."""

    class _FailingRouter:
        def classify(self, message, context):  # noqa: ANN001
            raise RuntimeError("LLM unavailable")

    store = ChatStore(":memory:")
    service = ChatService(store, _FailingRouter(), FakeExecutor(), FakeLLMClient())
    chunks, terminal = _collect_stream(service, "What is the plan?", "proj1")
    assert chunks  # degradation path still yields text
    assert terminal is not None
    assert terminal.get("done") is True


def test_stream_turn_suggestions_in_done_event():
    store = ChatStore(":memory:")
    _, terminal = _collect_stream(_service(store), "Hello", "proj1")
    assert isinstance(terminal.get("suggestions"), list)


# --------------------------------------------------------------------------- #
# Regression: an unreachable model must say so, not pretend it understood.
#
# _classify swallows every router exception. It used to degrade to
# confidence 0.0, which rendered the "unknown" template — telling the user
# "I understood your message, but I'm not sure how to help" when in truth
# Ollama was unreachable. That hid a fixable setup error behind a reply that
# blamed the user's phrasing.
# --------------------------------------------------------------------------- #


class _BrokenRouter:
    """Stands in for a router whose model cannot be reached."""

    model = "qwen3:4b"

    def classify(self, message, context):  # noqa: ANN001
        raise ConnectionError("Cannot reach Ollama at http://localhost:11434")


def test_unreachable_model_reports_setup_error():
    store = ChatStore(":memory:")
    service = ChatService(store, _BrokenRouter(), FakeExecutor(), FakeLLMClient())
    turn = service.handle_turn("test", "proj1")
    content = turn.message.content

    # Names the real cause and the remedy...
    assert "ollama" in content.lower()
    assert "Cannot reach Ollama" in content
    # ...and must NOT claim comprehension or offer intent suggestions.
    assert "I understood your message" not in content
    assert turn.action is None


def test_unreachable_model_reports_setup_error_when_streaming():
    store = ChatStore(":memory:")
    service = ChatService(store, _BrokenRouter(), FakeExecutor(), FakeLLMClient())
    chunks = [c for c in service.stream_turn("test", "proj1") if isinstance(c, str)]
    content = "".join(chunks)

    assert "Cannot reach Ollama" in content
    assert "I understood your message" not in content


def test_genuine_unknown_still_offers_suggestions():
    """A real low-confidence classification keeps the original fallback."""

    class _UnsureRouter:
        model = "qwen3:4b"

        def classify(self, message, context):  # noqa: ANN001
            return IntentClassification(intent="unknown", params={}, confidence=0.2)

    store = ChatStore(":memory:")
    service = ChatService(store, _UnsureRouter(), FakeExecutor(), FakeLLMClient())
    content = service.handle_turn("asdfgh", "proj1").message.content

    assert "I understood your message" in content
    assert "ollama" not in content.lower()


def test_french_message_does_not_crash():
    """detect_language can return 'fr'; every block must resolve (or fall back)."""

    class _SmallTalkRouter:
        model = "qwen3:4b"

        def classify(self, message, context):  # noqa: ANN001
            return IntentClassification(intent="smalltalk", params={}, confidence=0.9)

    store = ChatStore(":memory:")
    service = ChatService(store, _SmallTalkRouter(), FakeExecutor(), FakeLLMClient())
    turn = service.handle_turn("Bonjour, pouvez-vous m'aider ?", "proj1")
    assert turn.message.content.strip()
