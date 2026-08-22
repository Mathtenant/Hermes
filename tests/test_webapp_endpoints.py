"""Tests for Phase 4 FastAPI webapp endpoints (Phase 4.7)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from hermes_assistant.dashboard_html import DashboardData, RiskRow, load_dashboard_data
from hermes_assistant.jobqueue.jobs import JobStore
from hermes_assistant.risks.registry import RiskRegistry
from hermes_assistant.tasks.model import Task
from hermes_assistant.tasks.pendenzen import Pendenz, PendenzSource
from hermes_assistant.tasks.store import TaskStore
from hermes_assistant.webapp.server import _validate_safe_json, app

client = TestClient(app, raise_server_exceptions=False)

_NOW_STR = "2026-07-16T12:00:00Z"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def task_store() -> TaskStore:
    """In-memory TaskStore with one task and one pendenz."""
    store = TaskStore(":memory:")
    store.create(Task(id="", title="Alpha task", node_kind="task"))
    store.create(
        Pendenz(
            id="",
            title="Clarify scope",
            source=PendenzSource.manual,
            priority="high",
        )
    )
    return store


@pytest.fixture()
def job_store() -> JobStore:
    return JobStore(":memory:")


@pytest.fixture()
def risk_registry() -> RiskRegistry:
    """In-memory RiskRegistry with one public risk and one confidential risk."""
    reg = RiskRegistry(":memory:")
    reg.create("Data breach", severity="high", likelihood=4)
    reg.create("Secret risk", confidential=True, owner="admin@example.com")
    return reg


@pytest.fixture()
def mock_load(task_store: TaskStore, job_store: JobStore, risk_registry: RiskRegistry, tmp_path: Path):
    """Patch server's load_dashboard_data with pre-built DashboardData objects.

    The DashboardData objects are built in the test thread here, so they never
    touch SQLite from a different thread (which would violate SQLite's
    check_same_thread constraint on ``:memory:`` connections).
    """
    # Pre-build all scopes we need in the test (same thread as fixture creation)
    _prebuilt: dict[str | None, DashboardData] = {}
    for scope in (None, "alpha", "beta", "nonexistent"):
        _prebuilt[scope] = load_dashboard_data(
            scope,
            task_store=task_store,
            job_store=job_store,
            risk_registry=risk_registry,
            projects_root=tmp_path,
        )

    def _fake(project_id: str | None = None, **kwargs: object) -> DashboardData:
        # Return pre-built object; falls back to "all projects" for unknown scopes
        return _prebuilt.get(project_id, _prebuilt[None])

    with patch("hermes_assistant.webapp.server.load_dashboard_data", side_effect=_fake):
        yield


# ---------------------------------------------------------------------------
# /api/health
# ---------------------------------------------------------------------------


def test_health_200() -> None:
    r = client.get("/api/health")
    assert r.status_code == 200


def test_health_status_ok() -> None:
    r = client.get("/api/health")
    assert r.json()["status"] == "ok"


def test_health_has_timestamp() -> None:
    r = client.get("/api/health")
    ts = r.json().get("timestamp", "")
    assert "T" in ts and "Z" in ts


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------


def test_csp_header_present() -> None:
    r = client.get("/api/health")
    csp = r.headers.get("content-security-policy", "")
    assert "default-src 'none'" in csp


def test_x_content_type_nosniff() -> None:
    r = client.get("/api/health")
    assert r.headers.get("x-content-type-options") == "nosniff"


def test_x_frame_options_deny() -> None:
    r = client.get("/api/health")
    assert r.headers.get("x-frame-options") == "DENY"


def test_referrer_policy_no_referrer() -> None:
    r = client.get("/api/health")
    assert r.headers.get("referrer-policy") == "no-referrer"


# ---------------------------------------------------------------------------
# /api/dashboard
# ---------------------------------------------------------------------------


def test_dashboard_200(mock_load: None) -> None:
    r = client.get("/api/dashboard")
    assert r.status_code == 200


def test_dashboard_content_type_json(mock_load: None) -> None:
    r = client.get("/api/dashboard")
    assert "application/json" in r.headers.get("content-type", "")


def test_dashboard_has_required_fields(mock_load: None) -> None:
    body = client.get("/api/dashboard").json()
    for field in ("generated_at", "timeline", "kanban", "pendenzen", "wbs", "reviews", "projects", "risks"):
        assert field in body, f"Missing field: {field}"


def test_dashboard_kanban_has_three_columns(mock_load: None) -> None:
    body = client.get("/api/dashboard").json()
    statuses = {col["status"] for col in body["kanban"]}
    assert "open" in statuses
    assert "closed" in statuses


def test_dashboard_pendenzen_count(mock_load: None) -> None:
    body = client.get("/api/dashboard").json()
    assert len(body["pendenzen"]) == 1


def test_dashboard_no_raw_notes(mock_load: None) -> None:
    text = client.get("/api/dashboard").text
    assert "raw_notes" not in text.lower()


def test_dashboard_no_evidence_quote(mock_load: None) -> None:
    text = client.get("/api/dashboard").text
    assert "evidence_quote" not in text.lower()


def test_dashboard_no_fix_suggestion(mock_load: None) -> None:
    text = client.get("/api/dashboard").text
    assert "fix_suggestion" not in text.lower()


def test_dashboard_no_absolute_path(mock_load: None) -> None:
    text = client.get("/api/dashboard").text
    # tmp_path paths like /var/folders/... might be in raw_notes, but since
    # those fields are excluded by Pydantic extra="forbid", this must be clean.
    assert "/Users/" not in text
    assert "/home/" not in text


def test_dashboard_scope_all_projects(mock_load: None) -> None:
    body = client.get("/api/dashboard").json()
    assert body["scope"] == "all projects"


def test_dashboard_project_id_sets_scope(mock_load: None) -> None:
    body = client.get("/api/dashboard?project_id=alpha").json()
    assert body["scope"] == "alpha"


def test_dashboard_unknown_project_still_200(mock_load: None) -> None:
    # load_dashboard_data returns data regardless of project_id (just changes scope)
    r = client.get("/api/dashboard?project_id=nonexistent")
    assert r.status_code == 200


def test_dashboard_load_error_returns_500() -> None:
    with patch(
        "hermes_assistant.webapp.server.load_dashboard_data",
        side_effect=RuntimeError("db error"),
    ):
        r = client.get("/api/dashboard")
    assert r.status_code == 500
    assert "db error" in r.json().get("detail", "")


# ---------------------------------------------------------------------------
# /api/refresh
# ---------------------------------------------------------------------------


def test_refresh_200(mock_load: None) -> None:
    r = client.get("/api/refresh")
    assert r.status_code == 200


def test_refresh_same_schema_as_dashboard(mock_load: None) -> None:
    r1 = client.get("/api/dashboard").json()
    r2 = client.get("/api/refresh").json()
    assert set(r1.keys()) == set(r2.keys())


def test_refresh_with_project_id(mock_load: None) -> None:
    r = client.get("/api/refresh?project_id=beta")
    assert r.status_code == 200
    assert r.json()["scope"] == "beta"


# ---------------------------------------------------------------------------
# Confidentiality guard (_validate_safe_json)
# ---------------------------------------------------------------------------


def test_validate_safe_json_clean() -> None:
    clean = DashboardData(generated_at=_NOW_STR).model_dump_json()
    assert _validate_safe_json(clean) == []


def test_validate_safe_json_catches_forbidden_field() -> None:
    dirty = '{"raw_notes": "leaked"}'
    violations = _validate_safe_json(dirty)
    assert any("raw_notes" in v for v in violations)


def test_validate_safe_json_catches_fs_path() -> None:
    dirty = '{"title": "/Users/secret/path"}'
    violations = _validate_safe_json(dirty)
    assert any("filesystem path" in v.lower() for v in violations)


def test_confidentiality_guard_causes_500() -> None:
    """When _validate_safe_json returns violations the endpoint must return 500."""
    good_data = DashboardData(generated_at=_NOW_STR)
    with patch("hermes_assistant.webapp.server.load_dashboard_data", return_value=good_data):
        with patch(
            "hermes_assistant.webapp.server._validate_safe_json",
            return_value=["raw_notes leaked"],
        ):
            r = client.get("/api/dashboard")
    assert r.status_code == 500
    # H2: detail must be generic — violation names must not reach the client.
    detail = r.json().get("detail", "")
    assert detail == "Internal error"
    assert "raw_notes" not in detail


# ---------------------------------------------------------------------------
# SPA fallback
# ---------------------------------------------------------------------------


def test_root_returns_html_or_503() -> None:
    r = client.get("/")
    assert r.status_code in (200, 503)
    if r.status_code == 200:
        assert "text/html" in r.headers.get("content-type", "")


def test_unknown_path_spa_fallback() -> None:
    r = client.get("/projects/alpha")
    # Either serves index.html (200) or tells us UI isn't built (503)
    assert r.status_code in (200, 503)


# ---------------------------------------------------------------------------
# Pydantic model guard (extra="forbid")
# ---------------------------------------------------------------------------


def test_dashboard_data_extra_forbid() -> None:
    """DashboardData must reject extra fields to prevent confidential field injection."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DashboardData(generated_at=_NOW_STR, raw_notes="LEAK")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Risk Registry — dashboard risks field
# ---------------------------------------------------------------------------


def test_dashboard_risks_field_present(mock_load: None) -> None:
    body = client.get("/api/dashboard").json()
    assert "risks" in body
    assert isinstance(body["risks"], list)


def test_dashboard_risks_contains_public_risk(mock_load: None) -> None:
    body = client.get("/api/dashboard").json()
    titles = [r["title"] for r in body["risks"]]
    assert "Data breach" in titles


def test_dashboard_risks_excludes_confidential(mock_load: None) -> None:
    body = client.get("/api/dashboard").json()
    titles = [r["title"] for r in body["risks"]]
    assert "Secret risk" not in titles


def test_dashboard_risks_score_computed(mock_load: None) -> None:
    body = client.get("/api/dashboard").json()
    risk = next(r for r in body["risks"] if r["title"] == "Data breach")
    # high=3, likelihood=4 → score=12
    assert risk["score"] == 12


def test_dashboard_risks_row_fields(mock_load: None) -> None:
    body = client.get("/api/dashboard").json()
    risk = body["risks"][0]
    for field in ("id", "title", "severity", "likelihood", "status", "score", "updated_at"):
        assert field in risk, f"Missing RiskRow field: {field}"


def test_risk_row_extra_forbid() -> None:
    """RiskRow must reject extra fields (extra='forbid')."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RiskRow(
            id="x", title="t", severity="low", likelihood=1,
            status="open", score=1, updated_at="2026-01-01T00:00:00Z",
            raw_notes="LEAK",  # type: ignore[call-arg]
        )


def test_dashboard_risks_no_owner_email(mock_load: None) -> None:
    """Owner email from confidential risk must not appear in the response."""
    text = client.get("/api/dashboard").text
    assert "admin@example.com" not in text
