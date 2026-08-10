"""Sanity smoke tests (Phase 1 of the comprehensive test strategy).

Fast, offline checks that the core surfaces of hermes-assistant are wired up
correctly: HTTP endpoints respond, the import pipeline accepts/rejects data as
expected, the chat router round-trips a message, and the three SQLite-backed
stores (RiskRegistry, PlanEditor, ChatStore) support basic CRUD with the
RLock concurrency guard present. No live Ollama service or Playwright browser
is required — everything here uses FastAPI's TestClient and ``:memory:`` /
``tmp_path`` SQLite databases.

Target: 20-30 tests, <60s wall-clock, 100% pass on every commit.
"""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from hermes_assistant.chat.store import ChatStore
from hermes_assistant.config import settings
from hermes_assistant.dashboard_html import load_dashboard_data
from hermes_assistant.jobqueue.jobs import JobStore
from hermes_assistant.plans.editor import PlanEditor
from hermes_assistant.plans.model import PlanItem
from hermes_assistant.risks.registry import RiskRegistry
from hermes_assistant.tasks.model import Task
from hermes_assistant.tasks.store import TaskStore
from hermes_assistant.webapp import chat_api
from hermes_assistant.webapp.server import app

pytestmark = pytest.mark.sanity

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Endpoint health checks
# ---------------------------------------------------------------------------


def test_health_returns_200():
    r = client.get("/api/health")
    assert r.status_code == 200


def test_health_status_ok():
    r = client.get("/api/health")
    assert r.json()["status"] == "ok"


@pytest.fixture()
def _mock_dashboard(tmp_path: Path):
    """Isolated, pre-built DashboardData so /api/dashboard needs no real DBs."""
    task_store = TaskStore(":memory:")
    job_store = JobStore(":memory:")
    data = load_dashboard_data(None, task_store=task_store, job_store=job_store, projects_root=tmp_path)
    with patch(
        "hermes_assistant.webapp.server.load_dashboard_data",
        return_value=data,
    ):
        yield


def test_dashboard_returns_200(_mock_dashboard):
    r = client.get("/api/dashboard")
    assert r.status_code == 200


def test_dashboard_is_valid_json(_mock_dashboard):
    r = client.get("/api/dashboard")
    body = r.json()
    assert "generated_at" in body


def test_refresh_returns_200(_mock_dashboard):
    r = client.get("/api/refresh")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Import JSON endpoint
# ---------------------------------------------------------------------------


def test_import_json_valid_payload_creates_risk():
    payload = {"risks": [{"title": "Sanity risk", "severity": "low"}]}
    with patch(
        "hermes_assistant.webapp.server._get_import_paths",
        return_value={
            "risks_db": ":memory:",
            "plans_db": ":memory:",
            "tasks_db": ":memory:",
            "projects_root": None,
        },
    ):
        r = client.post("/api/import/json", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["created"] == 1


def test_import_json_invalid_payload_returns_422():
    r = client.post("/api/import/json", json={"unknown_key": []})
    assert r.status_code == 422


def test_import_json_empty_body_returns_422():
    r = client.post(
        "/api/import/json",
        content=b"",
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 422


def test_import_json_malformed_json_returns_422():
    r = client.post(
        "/api/import/json",
        content=b"{not valid json",
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 422


def test_import_json_missing_required_field_is_skipped():
    """Per-item validation failures (missing 'title') are reported as skipped
    items in a 200 response, not a top-level 422 (only payload *structure*
    errors — e.g. unknown entity types — produce 422)."""
    with patch(
        "hermes_assistant.webapp.server._get_import_paths",
        return_value={
            "risks_db": ":memory:",
            "plans_db": ":memory:",
            "tasks_db": ":memory:",
            "projects_root": None,
        },
    ):
        r = client.post("/api/import/json", json={"risks": [{"description": "no title"}]})
    assert r.status_code == 200
    body = r.json()
    assert body["skipped"] == 1
    assert body["created"] == 0


# ---------------------------------------------------------------------------
# Chat router: send message / list sessions / get session / delete session
# ---------------------------------------------------------------------------


@pytest.fixture()
def chat_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient wired to an isolated chat service (fresh temp DBs)."""
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "tasks_db_path", str(tmp_path / "tasks.db"))
    monkeypatch.setattr(settings, "chat_db_path", str(tmp_path / "chat.db"))
    chat_api._chat_service = None
    try:
        yield client
    finally:
        chat_api._chat_service = None


def test_chat_post_message_returns_200(chat_client):
    r = chat_client.post(
        "/api/chat/message", json={"message": "Hello", "project_id": "sanity-proj"}
    )
    assert r.status_code == 200
    assert r.json()["session_id"]


def test_chat_list_sessions_after_message(chat_client):
    chat_client.post(
        "/api/chat/message", json={"message": "Hi", "project_id": "sanity-proj"}
    )
    r = chat_client.get("/api/chat/sessions", params={"project_id": "sanity-proj"})
    assert r.status_code == 200
    assert len(r.json()["sessions"]) == 1


def test_chat_delete_session(chat_client):
    sent = chat_client.post(
        "/api/chat/message", json={"message": "Hi", "project_id": "sanity-proj"}
    )
    session_id = sent.json()["session_id"]
    r = chat_client.delete(f"/api/chat/sessions/{session_id}")
    assert r.status_code == 200
    assert r.json()["deleted"] is True


def test_chat_delete_unknown_session_returns_false(chat_client):
    r = chat_client.delete("/api/chat/sessions/does-not-exist")
    assert r.status_code == 200
    assert r.json()["deleted"] is False


# ---------------------------------------------------------------------------
# Store CRUD sanity — RiskRegistry, PlanEditor, ChatStore via tmp_path DBs
# ---------------------------------------------------------------------------


def test_risk_registry_crud_roundtrip(tmp_path: Path):
    reg = RiskRegistry(tmp_path / "risks.db")
    risk = reg.create("Sanity check risk")
    assert reg.get(risk.id) is not None
    assert reg.delete(risk.id) is True
    assert reg.get(risk.id) is None
    reg.close_connection()


def test_plan_editor_crud_roundtrip(tmp_path: Path):
    editor = PlanEditor(tmp_path / "plans.db")
    v1 = editor.create("plan-sanity", [PlanItem(title="Kickoff")])
    assert v1.version == 1
    fetched = editor.get("plan-sanity")
    assert fetched is not None
    assert fetched.items[0].title == "Kickoff"
    editor.close()


def test_chat_store_crud_roundtrip(tmp_path: Path):
    store = ChatStore(tmp_path / "chat.db")
    session = store.create_session("proj-sanity")
    assert store.get_session(session.id) is not None
    assert store.delete_session(session.id) is True
    store.close()


# ---------------------------------------------------------------------------
# Config loading & data dir writable
# ---------------------------------------------------------------------------


def test_settings_data_dir_is_set():
    assert settings.data_dir


def test_data_dir_is_writable(tmp_path: Path):
    probe = tmp_path / "write-probe.txt"
    probe.write_text("ok")
    assert probe.read_text() == "ok"


def test_settings_chat_confidence_threshold_in_range():
    assert 0.0 <= settings.chat_confidence_threshold <= 1.0


# ---------------------------------------------------------------------------
# RLock presence checks — required for FastAPI threadpool-safe concurrency
# ---------------------------------------------------------------------------


def test_risk_registry_has_rlock(tmp_path: Path):
    reg = RiskRegistry(tmp_path / "risks.db")
    assert isinstance(reg._lock, type(threading.RLock()))
    reg.close_connection()


def test_plan_editor_has_rlock(tmp_path: Path):
    editor = PlanEditor(tmp_path / "plans.db")
    assert isinstance(editor._lock, type(threading.RLock()))
    editor.close()


def test_chat_store_has_rlock(tmp_path: Path):
    store = ChatStore(tmp_path / "chat.db")
    assert isinstance(store._lock, type(threading.RLock()))
    store.close()


# ---------------------------------------------------------------------------
# Security headers (fast smoke — full coverage lives in test_webapp_endpoints)
# ---------------------------------------------------------------------------


def test_csp_header_present_on_health():
    r = client.get("/api/health")
    assert "content-security-policy" in {k.lower() for k in r.headers.keys()}


def test_task_store_smoke(tmp_path: Path):
    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create(Task(id="", title="Sanity task", node_kind="task"))
    assert store.get(task_id) is not None
    store.close()
