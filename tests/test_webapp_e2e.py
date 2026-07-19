"""Phase 4 webapp end-to-end flow tests (non-Playwright).

These tests exercise critical multi-step user flows by making sequential HTTP
requests through the FastAPI TestClient, verifying that:
  - Project list → project detail navigation works
  - Scoped dashboard data reflects the selected project
  - Pendenzen filter logic holds in the API response
  - Review drill-down data is present in the response
  - Confidentiality guards hold across all screens
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from hermes_assistant.dashboard_html import DashboardData, load_dashboard_data
from hermes_assistant.jobqueue.jobs import JobStore
from hermes_assistant.tasks.model import Task
from hermes_assistant.tasks.pendenzen import Pendenz, PendenzSource
from hermes_assistant.tasks.store import TaskStore
from hermes_assistant.webapp.server import app

client = TestClient(app, raise_server_exceptions=False)

_NOW_STR = "2026-07-16T12:00:00Z"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def rich_task_store() -> TaskStore:
    """TaskStore with tasks across multiple statuses and several pendenzen."""
    store = TaskStore(":memory:")
    root = store.create(Task(id="", title="Project Alpha root", node_kind="task"))
    store.create(Task(id="", title="Sub-task A", node_kind="task", parent_id=root))
    store.create(Task(id="", title="Sub-task B", node_kind="task", parent_id=root))
    closed_id = store.create(Task(id="", title="Completed task", node_kind="task"))
    store.close_task(closed_id)
    store.create(Pendenz(id="", title="Blocker: missing sign-off", source=PendenzSource.review, priority="blocker"))
    store.create(Pendenz(id="", title="High: schedule kickoff", source=PendenzSource.meeting, priority="high"))
    store.create(Pendenz(id="", title="Medium: clarify budget", source=PendenzSource.manual, priority="medium"))
    return store


@pytest.fixture()
def job_store() -> JobStore:
    return JobStore(":memory:")


@pytest.fixture()
def mock_all(rich_task_store: TaskStore, job_store: JobStore, tmp_path: Path):
    """Patch load_dashboard_data with pre-built DashboardData per scope."""
    _cache: dict[str | None, DashboardData] = {}
    for scope in (None, "alpha", "beta"):
        _cache[scope] = load_dashboard_data(
            scope,
            task_store=rich_task_store,
            job_store=job_store,
            projects_root=tmp_path,
        )

    def _fake(project_id: str | None = None, **kw: object) -> DashboardData:
        return _cache.get(project_id, _cache[None])

    with patch("hermes_assistant.webapp.server.load_dashboard_data", side_effect=_fake):
        yield


# ---------------------------------------------------------------------------
# Flow 1: Project list → project detail
# ---------------------------------------------------------------------------


def test_flow_project_list_loads(mock_all: None) -> None:
    """GET /api/dashboard returns the project list in the response."""
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    body = r.json()
    assert "projects" in body


def test_flow_project_detail_scoped(mock_all: None) -> None:
    """Drilling into a project sets scope to the project_id."""
    r = client.get("/api/dashboard?project_id=alpha")
    assert r.status_code == 200
    assert r.json()["scope"] == "alpha"


def test_flow_project_detail_has_kanban(mock_all: None) -> None:
    r = client.get("/api/dashboard?project_id=alpha")
    body = r.json()
    assert "kanban" in body
    statuses = {col["status"] for col in body["kanban"]}
    assert "open" in statuses
    assert "closed" in statuses


def test_flow_project_detail_has_wbs(mock_all: None) -> None:
    r = client.get("/api/dashboard?project_id=alpha")
    body = r.json()
    assert "wbs" in body
    assert isinstance(body["wbs"], list)


def test_flow_project_detail_has_timeline(mock_all: None) -> None:
    r = client.get("/api/dashboard?project_id=alpha")
    body = r.json()
    assert "timeline" in body
    assert isinstance(body["timeline"], list)


# ---------------------------------------------------------------------------
# Flow 2: Pendenzen — three pendenzen with distinct sources + priorities
# ---------------------------------------------------------------------------


def test_flow_pendenzen_count(mock_all: None) -> None:
    """All three pendenzen are present in the response."""
    body = client.get("/api/dashboard").json()
    assert len(body["pendenzen"]) == 3


def test_flow_pendenzen_sorted_by_priority(mock_all: None) -> None:
    """Pendenzen must be returned blocker → high → medium (ascending rank)."""
    rows = client.get("/api/dashboard").json()["pendenzen"]
    rank = {"blocker": 0, "high": 1, "medium": 2, "low": 3}
    ranks = [rank.get(r["priority"], 99) for r in rows]
    assert ranks == sorted(ranks), f"Wrong order: {ranks}"


def test_flow_pendenzen_sources_present(mock_all: None) -> None:
    rows = client.get("/api/dashboard").json()["pendenzen"]
    sources = {r["source"] for r in rows}
    assert "review" in sources
    assert "meeting" in sources
    assert "manual" in sources


def test_flow_pendenzen_no_forbidden_fields(mock_all: None) -> None:
    text = client.get("/api/dashboard").text
    for field in ("raw_notes", "evidence_quote", "rationale", "assumptions"):
        assert field not in text.lower(), f"Forbidden field {field!r} leaked"


# ---------------------------------------------------------------------------
# Flow 3: Reviews screen (no completed reviews in this fixture)
# ---------------------------------------------------------------------------


def test_flow_reviews_empty(mock_all: None) -> None:
    """No completed jobs → reviews list is empty but endpoint is 200."""
    body = client.get("/api/dashboard").json()
    assert body["reviews"] == []


# ---------------------------------------------------------------------------
# Flow 4: Refresh endpoint returns same schema as /api/dashboard
# ---------------------------------------------------------------------------


def test_flow_refresh_matches_dashboard(mock_all: None) -> None:
    dash = client.get("/api/dashboard").json()
    ref = client.get("/api/refresh").json()
    # Same top-level keys
    assert set(dash.keys()) == set(ref.keys())


def test_flow_refresh_scoped(mock_all: None) -> None:
    r = client.get("/api/refresh?project_id=beta")
    assert r.status_code == 200
    assert r.json()["scope"] == "beta"


# ---------------------------------------------------------------------------
# Flow 5: Security across all endpoints
# ---------------------------------------------------------------------------


def test_flow_all_endpoints_have_csp(mock_all: None) -> None:
    for path in ("/api/health", "/api/dashboard", "/api/refresh"):
        r = client.get(path)
        csp = r.headers.get("content-security-policy", "")
        assert "default-src 'none'" in csp, f"CSP missing on {path}"


def test_flow_no_external_url_in_any_response(mock_all: None) -> None:
    import re
    _ext = re.compile(r"https?://(?!localhost)")
    for path in ("/api/health", "/api/dashboard", "/api/refresh"):
        text = client.get(path).text
        assert not _ext.search(text), f"External URL in response to {path}"


def test_flow_html_served_for_spa_path(mock_all: None) -> None:
    """Non-API, non-static paths return HTML (SPA fallback) or 503."""
    r = client.get("/pendenzen")
    assert r.status_code in (200, 503)
