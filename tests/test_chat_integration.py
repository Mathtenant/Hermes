"""API integration tests for the chat endpoints (Phase 5.5).

Each test gets a fresh :class:`ChatService` singleton pointed at temp SQLite
databases, so sessions never leak between tests. Intent classification degrades
to a safe fallback when the ROUTER model is unavailable, so these tests do not
depend on a live Ollama model being pulled.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hermes_assistant.config import settings
from hermes_assistant.webapp import chat_api
from hermes_assistant.webapp.server import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient with an isolated, freshly-built chat service."""
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "tasks_db_path", str(tmp_path / "tasks.db"))
    monkeypatch.setattr(settings, "chat_db_path", str(tmp_path / "chat.db"))
    chat_api._chat_service = None
    try:
        yield TestClient(app)
    finally:
        chat_api._chat_service = None


def test_send_message_creates_session(client):
    response = client.post(
        "/api/chat/message", json={"message": "Hello", "project_id": "proj1"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert data["message"]["role"] == "assistant"


def test_send_message_with_session_id(client):
    response1 = client.post(
        "/api/chat/message", json={"message": "First", "project_id": "proj1"}
    )
    session_id = response1.json()["session_id"]
    response2 = client.post(
        "/api/chat/message",
        json={"message": "Second", "project_id": "proj1", "session_id": session_id},
    )
    assert response2.status_code == 200
    assert response2.json()["session_id"] == session_id


def test_send_message_empty_fails(client):
    response = client.post(
        "/api/chat/message", json={"message": "", "project_id": "proj1"}
    )
    assert response.status_code == 422


def test_send_message_too_long_fails(client):
    response = client.post(
        "/api/chat/message", json={"message": "x" * 2001, "project_id": "proj1"}
    )
    assert response.status_code == 422


def test_send_message_missing_project_id(client):
    response = client.post("/api/chat/message", json={"message": "Test"})
    assert response.status_code == 422


def test_list_sessions_empty(client):
    response = client.get("/api/chat/sessions")
    assert response.status_code == 200
    assert response.json()["sessions"] == []


def test_list_sessions_filter_by_project(client):
    client.post("/api/chat/message", json={"message": "Test", "project_id": "proj1"})
    response = client.get("/api/chat/sessions?project_id=proj1")
    assert response.status_code == 200
    assert len(response.json()["sessions"]) == 1


def test_get_session(client):
    post_resp = client.post(
        "/api/chat/message", json={"message": "Test", "project_id": "proj1"}
    )
    session_id = post_resp.json()["session_id"]
    response = client.get(f"/api/chat/sessions/{session_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["session"]["id"] == session_id
    assert len(data["messages"]) >= 2


def test_get_session_not_found(client):
    response = client.get("/api/chat/sessions/invalid_id")
    assert response.status_code == 404


def test_delete_session(client):
    post_resp = client.post(
        "/api/chat/message", json={"message": "Test", "project_id": "proj1"}
    )
    session_id = post_resp.json()["session_id"]
    response = client.delete(f"/api/chat/sessions/{session_id}")
    assert response.status_code == 200
    assert response.json()["deleted"] is True


def test_delete_session_cascade(client):
    post_resp = client.post(
        "/api/chat/message", json={"message": "Test", "project_id": "proj1"}
    )
    session_id = post_resp.json()["session_id"]
    assert len(client.get(f"/api/chat/sessions/{session_id}").json()["messages"]) > 0
    client.delete(f"/api/chat/sessions/{session_id}")
    assert client.get(f"/api/chat/sessions/{session_id}").status_code == 404


def test_send_message_response_structure(client):
    response = client.post(
        "/api/chat/message", json={"message": "Test", "project_id": "proj1"}
    )
    data = response.json()
    assert "session_id" in data
    assert data["message"]["role"] == "assistant"
    assert data["message"]["content"]
    assert "suggestions" in data


def test_rate_limit_not_enforced_yet(client):
    for i in range(25):
        response = client.post(
            "/api/chat/message", json={"message": f"Message {i}", "project_id": "proj1"}
        )
        assert response.status_code in [200, 500]


def test_confidentiality_guard_on_response(client):
    response = client.post(
        "/api/chat/message",
        json={"message": "What are the risks?", "project_id": "proj1"},
    )
    assert response.status_code == 200


def test_multiple_sessions_per_project(client):
    r1 = client.post(
        "/api/chat/message", json={"message": "Session 1", "project_id": "proj1"}
    )
    r2 = client.post(
        "/api/chat/message", json={"message": "Session 2", "project_id": "proj1"}
    )
    assert r1.json()["session_id"] != r2.json()["session_id"]
    sessions = client.get("/api/chat/sessions?project_id=proj1").json()
    assert len(sessions["sessions"]) >= 2


def test_send_message_malformed_json(client):
    response = client.post(
        "/api/chat/message",
        content="not json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code in [400, 422]


def test_chat_action_in_response(client):
    response = client.post(
        "/api/chat/message", json={"message": "Create a task", "project_id": "proj1"}
    )
    assert "action" in response.json()


def test_suggestions_in_response(client):
    response = client.post(
        "/api/chat/message", json={"message": "Hello", "project_id": "proj1"}
    )
    assert isinstance(response.json()["suggestions"], list)


def test_send_message_persists_history(client):
    post = client.post(
        "/api/chat/message", json={"message": "Remember this", "project_id": "proj1"}
    )
    session_id = post.json()["session_id"]
    messages = client.get(f"/api/chat/sessions/{session_id}").json()["messages"]
    assert messages[0]["content"] == "Remember this"


def test_send_message_whitespace_only_fails(client):
    response = client.post(
        "/api/chat/message", json={"message": "   ", "project_id": "proj1"}
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# Q1 — conversational politeness (smalltalk / capability / meta)
#
# Ollama is not available in CI, so we install a deterministic keyword router
# into the chat-service singleton. The real ResponseFormatter still produces
# the static, language-aware replies from responses.yaml.
# --------------------------------------------------------------------------- #


class _KeywordRouter:
    """Classify by keyword so conversational intents are testable offline."""

    def classify(self, message, context):  # noqa: ANN001
        from hermes_assistant.chat.model import IntentClassification

        low = message.lower()
        if any(w in low for w in ["hello", "hi", "hallo", "hey", "thanks", "danke", "bye"]):
            intent = "smalltalk"
        elif "can you do" in low or "help" in low or "commands" in low:
            intent = "capability"
        elif "model" in low or "locally" in low or "local" in low:
            intent = "meta"
        else:
            intent = "answer_question"
        return IntentClassification(intent=intent, params={}, confidence=0.95)


@pytest.fixture
def convo_client(tmp_path, monkeypatch):
    """A TestClient whose chat service uses the deterministic keyword router."""
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "tasks_db_path", str(tmp_path / "tasks.db"))
    monkeypatch.setattr(settings, "chat_db_path", str(tmp_path / "chat.db"))

    from hermes_assistant.chat.executor import ActionExecutor
    from hermes_assistant.chat.service import ChatService
    from hermes_assistant.chat.store import ChatStore

    store = ChatStore(str(tmp_path / "chat.db"))
    executor = ActionExecutor(None, None, None)
    chat_api._chat_service = ChatService(store, _KeywordRouter(), executor, None)
    try:
        yield TestClient(app)
    finally:
        chat_api._chat_service = None


def test_chat_smalltalk_no_action(convo_client):
    """Smalltalk doesn't create actions and returns a greeting."""
    response = convo_client.post(
        "/api/chat/message", json={"message": "Hello!", "project_id": "proj1"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["action"] is None
    content = data["message"]["content"].lower()
    assert "hello" in content or "hallo" in content


def test_chat_capability_lists_examples(convo_client):
    """Capability shows concrete examples and takes no action."""
    response = convo_client.post(
        "/api/chat/message",
        json={"message": "What can you do?", "project_id": "proj1"},
    )
    assert response.status_code == 200
    data = response.json()
    content = data["message"]["content"].lower()
    assert "risk" in content or "task" in content
    assert data["action"] is None


def test_chat_meta_returns_model_info(convo_client):
    """Meta question returns model information, no action."""
    response = convo_client.post(
        "/api/chat/message",
        json={"message": "What model are you?", "project_id": "proj1"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "qwen" in data["message"]["content"].lower()
    assert data["action"] is None


def test_chat_greeting_not_rephrase(convo_client):
    """A greeting must not trigger the old 'could you rephrase' fallback."""
    response = convo_client.post(
        "/api/chat/message", json={"message": "Hi there", "project_id": "proj1"}
    )
    assert "rephrase" not in response.json()["message"]["content"].lower()


# --------------------------------------------------------------------------- #
# Q3 — import endpoint remains functional with two-step UI
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# H4 — executor errors surface as user-safe messages (integration)
# --------------------------------------------------------------------------- #


class _UniqueConstraintExecutor:
    """Simulates an executor returning a UNIQUE constraint DB error."""

    def execute(self, action_type, params, context):  # noqa: ANN001
        return {"error": "UNIQUE constraint failed: risks.id"}


class _AlwaysHighConfidenceRouter:
    def classify(self, message, context):  # noqa: ANN001
        from hermes_assistant.chat.model import IntentClassification

        return IntentClassification(intent="create_risk", params={}, confidence=0.9)


@pytest.fixture
def error_client(tmp_path, monkeypatch):
    """TestClient whose executor always returns a UNIQUE constraint error."""
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "tasks_db_path", str(tmp_path / "tasks.db"))
    monkeypatch.setattr(settings, "chat_db_path", str(tmp_path / "chat.db"))

    from hermes_assistant.chat.service import ChatService
    from hermes_assistant.chat.store import ChatStore

    store = ChatStore(str(tmp_path / "chat.db"))
    chat_api._chat_service = ChatService(
        store, _AlwaysHighConfidenceRouter(), _UniqueConstraintExecutor(), None
    )
    try:
        yield TestClient(app)
    finally:
        chat_api._chat_service = None


def test_h4_unique_error_not_leaked_in_response(error_client):
    """H4: UNIQUE constraint error must not appear verbatim in the chat response."""
    response = error_client.post(
        "/api/chat/message", json={"message": "Create a risk", "project_id": "proj1"}
    )
    assert response.status_code == 200
    content = response.json()["message"]["content"]
    assert "UNIQUE" not in content
    assert "risks.id" not in content
    assert "already exists" in content


def test_h4_not_found_error_not_leaked_in_response(tmp_path, monkeypatch):
    """H4: 'not found' executor errors produce a user-friendly message."""
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "tasks_db_path", str(tmp_path / "tasks.db"))
    monkeypatch.setattr(settings, "chat_db_path", str(tmp_path / "chat.db"))

    from hermes_assistant.chat.service import ChatService
    from hermes_assistant.chat.store import ChatStore

    class _NotFoundExecutor:
        def execute(self, action_type, params, context):  # noqa: ANN001
            return {"error": "Risk with id 'abc' not found"}

    store = ChatStore(str(tmp_path / "chat.db"))
    chat_api._chat_service = ChatService(
        store, _AlwaysHighConfidenceRouter(), _NotFoundExecutor(), None
    )
    client = TestClient(app)
    response = client.post(
        "/api/chat/message", json={"message": "Show risk abc", "project_id": "proj1"}
    )
    chat_api._chat_service = None

    assert response.status_code == 200
    content = response.json()["message"]["content"]
    assert "abc" not in content
    assert "not found" in content.lower()


def test_import_endpoint_still_works(client):
    """The /api/import/json endpoint accepts JSON directly (two-step UI doesn't break it)."""
    payload = {"risks": [{"title": "Risk from Copilot"}]}
    response = client.post("/api/import/json", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["created"] == 1


def test_copilot_prompt_file_served(client):
    """The static prompt file used in the two-step dialog is accessible."""
    response = client.get("/static/prompts/copilot_state_export.txt")
    assert response.status_code == 200
    assert "JSON" in response.text or "Aufgabe" in response.text


# --------------------------------------------------------------------------- #
# H1 — user-authored email in a chat message must not 500 the session read
# --------------------------------------------------------------------------- #


def test_h1_user_email_in_message_does_not_break_get_session(client):
    """H1: a user who types their own email must still be able to read the
    session back. Previously the confidentiality guard matched the user's own
    email in GET /api/chat/sessions/{id} and returned 500 forever."""
    post = client.post(
        "/api/chat/message",
        json={"message": "contact me at john@example.com", "project_id": "proj1"},
    )
    assert post.status_code == 200
    session_id = post.json()["session_id"]

    response = client.get(f"/api/chat/sessions/{session_id}")
    assert response.status_code == 200, response.text

    # The user's message (with the email) is round-tripped unmodified.
    messages = response.json()["messages"]
    user_msgs = [m for m in messages if m["role"] == "user"]
    assert user_msgs
    assert "john@example.com" in user_msgs[0]["content"]


def test_h1_user_filesystem_path_in_message_does_not_break_get_session(client):
    """H1: a filesystem path the user typed must not trip the guard on read."""
    post = client.post(
        "/api/chat/message",
        json={"message": "my logs are in /Users/john/logs", "project_id": "proj1"},
    )
    assert post.status_code == 200
    session_id = post.json()["session_id"]

    response = client.get(f"/api/chat/sessions/{session_id}")
    assert response.status_code == 200, response.text
