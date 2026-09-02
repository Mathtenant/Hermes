"""Tests for Phase 4 FastAPI webapp endpoints (Phase 4.7)."""
from __future__ import annotations

import tomllib
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from hermes_assistant import __version__
from hermes_assistant.dashboard_html import (
    DashboardData,
    PendenzRow,
    RiskRow,
    load_dashboard_data,
)
from hermes_assistant.jobqueue.jobs import JobStore
from hermes_assistant.risks.registry import RiskRegistry
from hermes_assistant.tasks.model import Task
from hermes_assistant.tasks.pendenzen import Pendenz, PendenzSource
from hermes_assistant.tasks.store import TaskStore
from hermes_assistant.webapp.server import (
    _classify_violations,
    _validate_safe_json,
    app,
)

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


def test_health_reports_version() -> None:
    """/api/health carries the running version — the dashboard renders it."""
    r = client.get("/api/health")
    assert r.json()["version"] == __version__


def test_version_matches_pyproject() -> None:
    """``__version__`` is the single source of truth the UI displays.

    pyproject.toml carries its own copy for packaging; this guards against the
    two drifting so the dashboard can never show a stale version.
    """
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with pyproject.open("rb") as fh:
        declared = tomllib.load(fh)["project"]["version"]
    assert declared == __version__, (
        f"pyproject.toml version {declared!r} != "
        f"hermes_assistant.__version__ {__version__!r}"
    )


def test_setup_py_declares_no_version() -> None:
    """setup.py must not carry a third copy of the version.

    It is a package-discovery shim; ``[project]`` in pyproject.toml supplies the
    distribution metadata. A ``version=`` there would not fail any build — it is
    simply ignored — so it could drift from ``__version__`` unnoticed and ship a
    stale number in the wheel. Guard the absence rather than the agreement.
    """
    setup_py = Path(__file__).resolve().parents[1] / "setup.py"
    source = setup_py.read_text(encoding="utf-8")
    assert "version=" not in source, (
        "setup.py declares a version; delete it and let pyproject.toml's "
        "[project] table remain the single packaging source."
    )


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


def test_structural_violation_causes_500() -> None:
    """A forbidden *field name* is a code bug and must fail the response.

    A view model exposing something it never should cannot be salvaged by
    redaction, so this stays a hard failure.
    """
    good_data = DashboardData(generated_at=_NOW_STR)
    with patch("hermes_assistant.webapp.server.load_dashboard_data", return_value=good_data):
        with patch(
            "hermes_assistant.webapp.server._classify_violations",
            return_value=(["raw_notes leaked"], []),
        ):
            r = client.get("/api/dashboard")
    assert r.status_code == 500
    # H2: detail must be generic — violation names must not reach the client.
    detail = r.json().get("detail", "")
    assert detail == "Internal error"
    assert "raw_notes" not in detail


def test_content_violation_is_redacted_not_fatal() -> None:
    """An email in imported *content* must be scrubbed, not 500 the screen.

    Rows are stored verbatim, so failing here would make the dashboard
    unreachable on every request until the database was edited by hand — one
    imported meeting note could disable the product.
    """
    poisoned = DashboardData(
        generated_at=_NOW_STR,
        pendenzen=[
            PendenzRow(
                id="p1",
                title="Klaerung mit hans.muster@example.com",
                source="meeting",
                priority="medium",
                status="open",
            )
        ],
    )
    with patch(
        "hermes_assistant.webapp.server.load_dashboard_data", return_value=poisoned
    ):
        r = client.get("/api/dashboard")

    assert r.status_code == 200
    body = r.text
    assert "hans.muster@example.com" not in body
    assert "[E-Mail entfernt]" in body


def test_classify_violations_separates_field_names_from_values() -> None:
    structural, content = _classify_violations(
        '{"raw_notes": "x", "title": "a@b.com"}'
    )
    assert any("raw_notes" in v for v in structural)
    assert any("Email" in v for v in content)
    assert not structural[0].startswith("Email")


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


# ---------------------------------------------------------------------------
# POST /api/tasks/{id}/status — moving a card between kanban columns
#
# TaskStore.update() could always do this, but no route reached it, so the
# board was read-only: a card could be opened and read, never moved.
# ---------------------------------------------------------------------------


@pytest.fixture()
def status_db(tmp_path: Path):
    """A real on-disk TaskStore the route can reopen by path."""
    db = tmp_path / "tasks.db"
    store = TaskStore(str(db))
    task_id = store.create(Task(id="", title="Movable", node_kind="task"))
    store.close()
    # Patch the binding the route actually reads. `server.py` does
    # `from hermes_assistant.config import settings` at import time, so after
    # anything reloads the config module the two names refer to different
    # objects and patching the config one has no effect on the route.
    with patch("hermes_assistant.webapp.server.settings.tasks_db_path", str(db)):
        yield str(db), task_id


def test_set_task_status_moves_the_task(status_db) -> None:
    db, task_id = status_db
    resp = client.post(f"/api/tasks/{task_id}/status", json={"status": "closed"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "closed"

    store = TaskStore(db)
    try:
        assert store.get(task_id).status == "closed"
    finally:
        store.close()


def test_set_task_status_records_an_audit_entry(status_db) -> None:
    """The change must be attributable, not a silent overwrite."""
    db, task_id = status_db
    client.post(f"/api/tasks/{task_id}/status", json={"status": "blocked"})

    store = TaskStore(db)
    try:
        updates = [u for u in store.get(task_id).updates if u.field == "status"]
    finally:
        store.close()
    assert len(updates) == 1
    assert updates[0].old_value == "open"
    assert updates[0].new_value == "blocked"
    assert updates[0].changed_by == "dashboard"


@pytest.mark.parametrize("status", ["open", "closed", "blocked"])
def test_set_task_status_accepts_every_column(status_db, status: str) -> None:
    _, task_id = status_db
    resp = client.post(f"/api/tasks/{task_id}/status", json={"status": status})
    assert resp.status_code == 200
    assert resp.json()["status"] == status


@pytest.mark.parametrize(
    "body", [{"status": "done"}, {"status": ""}, {"status": None}, {}, {"other": "x"}]
)
def test_set_task_status_rejects_unknown_status(status_db, body: dict) -> None:
    """Only the three real statuses; anything else is a 422, never a write."""
    db, task_id = status_db
    assert client.post(f"/api/tasks/{task_id}/status", json=body).status_code == 422

    store = TaskStore(db)
    try:
        assert store.get(task_id).status == "open"  # untouched
    finally:
        store.close()


def test_set_task_status_rejects_a_non_object_body(status_db) -> None:
    _, task_id = status_db
    resp = client.post(f"/api/tasks/{task_id}/status", json=["closed"])
    assert resp.status_code == 422


def test_set_task_status_unknown_task_is_404(status_db) -> None:
    resp = client.post("/api/tasks/no-such-task/status", json={"status": "closed"})
    assert resp.status_code == 404


def test_set_task_status_response_carries_no_extra_fields(status_db) -> None:
    """Echoing the whole task would put description/metadata on the wire.

    Neither is filtered by the dashboard's field allowlist, and the board only
    needs enough to re-place the card.
    """
    _, task_id = status_db
    body = client.post(f"/api/tasks/{task_id}/status", json={"status": "closed"}).json()
    assert set(body) == {"id", "status", "wbs_number", "updated_at"}


# ---------------------------------------------------------------------------
# POST /api/schedule/{project}/items/{item}/owner
#
# The owner is the field an import gets wrong most often — a protocol names a
# team where the plan means a person. Fixing it had meant re-running the whole
# export.
# ---------------------------------------------------------------------------


@pytest.fixture()
def owner_project(tmp_path: Path):
    """A project directory holding one real schedule.json."""
    from hermes_assistant.scheduling.model import Schedule, ScheduledItem

    proj = tmp_path / "projects"
    (proj / "widget").mkdir(parents=True)
    schedule = Schedule(
        project_id="widget",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        items=[
            ScheduledItem(
                uid="hermes-widget-a@local", project_id="widget",
                project_label="Widget", item_id="a", title="Task A",
                kind="task", due=date(2026, 6, 1), owner="IT",
            )
        ],
    )
    (proj / "widget" / "schedule.json").write_text(
        schedule.model_dump_json(indent=2), encoding="utf-8"
    )
    with patch("hermes_assistant.webapp.server.settings.projects_path", str(proj)):
        yield proj / "widget" / "schedule.json"


def _stored_owner(sched_file: Path) -> str | None:
    from hermes_assistant.scheduling.model import Schedule

    sched = Schedule.model_validate_json(sched_file.read_text(encoding="utf-8"))
    return sched.items[0].owner


def test_set_owner_writes_through_to_disk(owner_project) -> None:
    resp = client.post(
        "/api/schedule/widget/items/a/owner", json={"owner": "Frau Meier"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["owner"] == "Frau Meier"
    assert _stored_owner(owner_project) == "Frau Meier"


def test_an_empty_owner_clears_the_assignment(owner_project) -> None:
    """"Nobody owns this" is a finding a lead needs to be able to record."""
    assert client.post(
        "/api/schedule/widget/items/a/owner", json={"owner": "  "}
    ).status_code == 200
    assert _stored_owner(owner_project) is None


def test_an_email_in_the_owner_is_redacted_not_stored(owner_project) -> None:
    """One pasted address would otherwise 500 the dashboard permanently.

    The response guard rejects an email anywhere in a payload, and the owner is
    rendered on every row of the plan — so it goes through the same redaction
    the importer applies, and the caller is told.
    """
    resp = client.post(
        "/api/schedule/widget/items/a/owner", json={"owner": "a.muster@example.com"}
    )
    assert resp.status_code == 200
    assert "@" not in resp.json()["owner"]
    assert resp.json()["redacted"]
    assert "@" not in (_stored_owner(owner_project) or "")


def test_owner_length_is_capped(owner_project) -> None:
    """A sentence in this field would be rendered on every row."""
    resp = client.post(
        "/api/schedule/widget/items/a/owner", json={"owner": "x" * 200}
    )
    assert resp.status_code == 422
    assert _stored_owner(owner_project) == "IT"  # untouched


@pytest.mark.parametrize("bad", [{"owner": 42}, {"owner": None}, ["x"]])
def test_owner_rejects_a_non_string(owner_project, bad) -> None:
    assert client.post(
        "/api/schedule/widget/items/a/owner", json=bad
    ).status_code == 422


def test_owner_rejects_an_unsafe_project_id(owner_project) -> None:
    """The id builds a path, so it must not be able to climb out."""
    resp = client.post(
        "/api/schedule/not a slug/items/a/owner", json={"owner": "X"}
    )
    assert resp.status_code == 422


def test_owner_unknown_project_is_404(owner_project) -> None:
    assert client.post(
        "/api/schedule/nosuch/items/a/owner", json={"owner": "X"}
    ).status_code == 404


def test_owner_unknown_item_is_404(owner_project) -> None:
    assert client.post(
        "/api/schedule/widget/items/nosuch/owner", json={"owner": "X"}
    ).status_code == 404
    assert _stored_owner(owner_project) == "IT"


def test_setting_an_owner_leaves_the_rest_of_the_schedule_intact(
    owner_project,
) -> None:
    """A rewrite of the file must not lose the fields it does not touch."""
    from hermes_assistant.scheduling.model import Schedule

    client.post("/api/schedule/widget/items/a/owner", json={"owner": "Neu"})
    sched = Schedule.model_validate_json(
        owner_project.read_text(encoding="utf-8")
    )
    item = sched.items[0]
    assert item.title == "Task A"
    assert str(item.due) == "2026-06-01"
    assert item.uid == "hermes-widget-a@local"


# ---------------------------------------------------------------------------
# Create routes — POST /api/todos, /api/tasks, /api/projects
#
# Everything on the dashboard arrived by import until now, which left it
# read-only for anything that came up between exports.
# ---------------------------------------------------------------------------


@pytest.fixture()
def create_env(tmp_path: Path):
    db = tmp_path / "tasks.db"
    proj = tmp_path / "projects"
    proj.mkdir()
    with patch("hermes_assistant.webapp.server.settings.tasks_db_path", str(db)), patch(
        "hermes_assistant.webapp.server.settings.projects_path", str(proj)
    ):
        yield db, proj


def _stored(db: Path, task_id: str):
    store = TaskStore(str(db))
    try:
        return store.get(task_id)
    finally:
        store.close()


def test_create_todo_lands_in_the_task_store(create_env) -> None:
    db, _ = create_env
    resp = client.post(
        "/api/todos",
        json={"title": "Angebot einholen", "owner": "Einkauf",
              "priority": "high", "due_date": "2026-10-10"},
    )
    assert resp.status_code == 200, resp.text

    todo = _stored(db, resp.json()["id"])
    assert todo.title == "Angebot einholen"
    assert todo.node_kind == "pendenz"
    assert todo.owner == "Einkauf"
    assert todo.priority == "high"
    assert str(todo.due_date) == "2026-10-10"


def test_a_hand_made_todo_is_marked_manual(create_env) -> None:
    """It has to be the same shape as an imported one, but say where it came
    from — otherwise a re-import cannot tell what it is safe to replace."""
    db, _ = create_env
    resp = client.post("/api/todos", json={"title": "X"})
    assert _stored(db, resp.json()["id"]).source == "manual"


def test_create_todo_requires_a_title(create_env) -> None:
    assert client.post("/api/todos", json={"title": "   "}).status_code == 422
    assert client.post("/api/todos", json={}).status_code == 422


@pytest.mark.parametrize("bad", ["urgent", "hoch", "", None])
def test_create_todo_rejects_an_unknown_priority(create_env, bad) -> None:
    assert client.post(
        "/api/todos", json={"title": "X", "priority": bad}
    ).status_code == 422


def test_an_unusable_due_date_is_reported_not_dropped(create_env) -> None:
    """A silently discarded deadline is worse than a rejected form."""
    resp = client.post("/api/todos", json={"title": "X", "due_date": "KW 47"})
    assert resp.status_code == 422
    assert "YYYY-MM-DD" in resp.json()["detail"]


def test_an_absent_due_date_is_fine(create_env) -> None:
    db, _ = create_env
    resp = client.post("/api/todos", json={"title": "X", "due_date": ""})
    assert resp.status_code == 200
    assert _stored(db, resp.json()["id"]).due_date is None


def test_hand_typed_text_is_redacted(create_env) -> None:
    """Hand-entered text is *more* likely to carry an address than imported
    text — somebody pasting a contact into a to-do would otherwise 500 the
    dashboard permanently."""
    db, _ = create_env
    resp = client.post(
        "/api/todos", json={"title": "Klaeren mit a.muster@example.com"}
    )
    assert resp.status_code == 200
    assert "@" not in resp.json()["title"]
    assert "@" not in _stored(db, resp.json()["id"]).title


def test_title_length_is_capped(create_env) -> None:
    assert client.post(
        "/api/todos", json={"title": "x" * 500}
    ).status_code == 422


def test_create_task_lands_in_the_tree(create_env) -> None:
    db, _ = create_env
    resp = client.post(
        "/api/tasks",
        json={"title": "Neues Arbeitspaket", "node_kind": "deliverable",
              "owner": "IT", "status": "blocked"},
    )
    assert resp.status_code == 200, resp.text
    task = _stored(db, resp.json()["id"])
    assert task.node_kind == "deliverable"
    assert task.status == "blocked"


def test_a_task_can_be_nested_under_an_existing_one(create_env) -> None:
    db, _ = create_env
    parent = client.post("/api/tasks", json={"title": "Phase"}).json()["id"]
    child = client.post(
        "/api/tasks", json={"title": "Unterpunkt", "parent_id": parent}
    ).json()["id"]
    assert _stored(db, child).parent_id == parent
    assert child in _stored(db, parent).children_ids


def test_a_task_cannot_be_orphaned_under_a_missing_parent(create_env) -> None:
    """It would show on the board but be absent from the WBS."""
    resp = client.post("/api/tasks", json={"title": "X", "parent_id": "nope"})
    assert resp.status_code == 404


@pytest.mark.parametrize("kind", ["pendenz", "assumption", "nonsense"])
def test_create_task_rejects_node_kinds_it_does_not_own(create_env, kind) -> None:
    """"pendenz" belongs to POST /api/todos; two routes for one thing drift.
    "assumption" holds notes the dashboard deliberately never renders."""
    assert client.post(
        "/api/tasks", json={"title": "X", "node_kind": kind}
    ).status_code == 422


def test_create_project_makes_a_directory(create_env) -> None:
    _, proj = create_env
    resp = client.post("/api/projects", json={"project_id": "neu-projekt"})
    assert resp.status_code == 200, resp.text
    assert (proj / "neu-projekt").is_dir()


def test_create_project_is_not_a_way_to_overwrite_one(create_env) -> None:
    client.post("/api/projects", json={"project_id": "a"})
    assert client.post("/api/projects", json={"project_id": "a"}).status_code == 409


@pytest.mark.parametrize("bad", ["../escaped", "a/b", "..", ".", "", "  "])
def test_create_project_rejects_an_unsafe_id(create_env, bad) -> None:
    """The id becomes a directory name."""
    _, proj = create_env
    assert client.post(
        "/api/projects", json={"project_id": bad}
    ).status_code == 422
    assert list(proj.parent.glob("escaped")) == []


@pytest.mark.parametrize(
    "endpoint", ["/api/todos", "/api/tasks", "/api/projects"]
)
def test_create_routes_reject_a_non_object_body(create_env, endpoint) -> None:
    assert client.post(endpoint, json=["x"]).status_code == 422


# ---------------------------------------------------------------------------
# Delete & restore (undo)
#
# Nothing was removable before these routes: the stores grew but never shrank,
# so a typo or a duplicate import was permanent. Both deletes are recoverable,
# which is what makes the UI's Undo button honest rather than decorative.
# ---------------------------------------------------------------------------


def _new_todo(title: str = "Wegwerfen") -> str:
    r = client.post("/api/todos", json={"title": title})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_deleting_a_todo_hides_it(create_env) -> None:
    db, _ = create_env
    tid = _new_todo()
    assert client.delete(f"/api/tasks/{tid}").status_code == 200
    assert _stored(db, tid) is None


def test_delete_returns_an_undo_token_that_restores(create_env) -> None:
    db, _ = create_env
    tid = _new_todo("Zurückholen")
    undo = client.delete(f"/api/tasks/{tid}").json()["undo"]

    assert client.post("/api/tasks/restore", json=undo).status_code == 200
    back = _stored(db, tid)
    assert back is not None
    assert back.title == "Zurückholen"


def test_restore_brings_back_the_whole_subtree(create_env) -> None:
    """Deleting a parent takes its children; undo must return all of them."""
    db, _ = create_env
    parent = client.post("/api/tasks", json={"title": "Paket"}).json()["id"]
    child = client.post(
        "/api/tasks", json={"title": "Unterpunkt", "parent_id": parent}
    ).json()["id"]

    body = client.delete(f"/api/tasks/{parent}").json()
    assert body["deleted"] == 2
    assert _stored(db, child) is None

    client.post("/api/tasks/restore", json=body["undo"])
    assert _stored(db, child) is not None


def test_deleting_an_unknown_task_is_404(create_env) -> None:
    assert client.delete("/api/tasks/does-not-exist").status_code == 404


def test_deleting_twice_is_404_the_second_time(create_env) -> None:
    """The row is already hidden, so there is nothing left to delete."""
    tid = _new_todo()
    assert client.delete(f"/api/tasks/{tid}").status_code == 200
    assert client.delete(f"/api/tasks/{tid}").status_code == 404


def test_restore_rejects_a_body_that_is_not_a_list_of_ids(create_env) -> None:
    assert client.post("/api/tasks/restore", json={"ids": "abc"}).status_code == 422
    assert client.post("/api/tasks/restore", json={"ids": [1, 2]}).status_code == 422


def test_a_deleted_todo_stops_counting_as_open(create_env) -> None:
    """The sidebar count reads through count_open, which must skip deleted rows."""
    db, _ = create_env
    tid = _new_todo()
    store = TaskStore(str(db))
    try:
        before = store.count_open()
    finally:
        store.close()

    client.delete(f"/api/tasks/{tid}")

    store = TaskStore(str(db))
    try:
        assert store.count_open() == before - 1
    finally:
        store.close()


# --- projects --------------------------------------------------------------


def test_deleting_a_project_moves_it_out_of_the_projects_dir(create_env) -> None:
    _, proj = create_env
    client.post("/api/projects", json={"project_id": "wegwerf"})
    assert client.delete("/api/projects/wegwerf").status_code == 200
    assert not (proj / "wegwerf").exists()


def test_a_deleted_project_keeps_the_users_own_files(create_env) -> None:
    """The directory holds documents Hermes did not create and cannot rebuild.

    This is the reason delete is a move and never an rmtree.
    """
    _, proj = create_env
    client.post("/api/projects", json={"project_id": "mitdatei"})
    (proj / "mitdatei" / "protokoll.txt").write_text("wichtig", encoding="utf-8")

    undo = client.delete("/api/projects/mitdatei").json()["undo"]
    trashed = proj.parent / ".trash" / undo["trash_name"] / "protokoll.txt"
    assert trashed.read_text(encoding="utf-8") == "wichtig"


def test_restoring_a_project_returns_its_files_intact(create_env) -> None:
    _, proj = create_env
    client.post("/api/projects", json={"project_id": "zurueck"})
    (proj / "zurueck" / "plan.txt").write_text("inhalt", encoding="utf-8")

    undo = client.delete("/api/projects/zurueck").json()["undo"]
    assert client.post("/api/projects/restore", json=undo).status_code == 200
    assert (proj / "zurueck" / "plan.txt").read_text(encoding="utf-8") == "inhalt"


def test_deleting_the_same_project_id_twice_does_not_clobber_the_first(
    create_env,
) -> None:
    """Recreate-then-delete must not overwrite the earlier copy in the trash."""
    _, proj = create_env
    client.post("/api/projects", json={"project_id": "wieder"})
    (proj / "wieder" / "a.txt").write_text("erste", encoding="utf-8")
    first = client.delete("/api/projects/wieder").json()["undo"]

    client.post("/api/projects", json={"project_id": "wieder"})
    (proj / "wieder" / "a.txt").write_text("zweite", encoding="utf-8")
    second = client.delete("/api/projects/wieder").json()["undo"]

    assert first["trash_name"] != second["trash_name"]
    trash = proj.parent / ".trash"
    assert (trash / first["trash_name"] / "a.txt").read_text(encoding="utf-8") == "erste"


def test_deleting_an_unknown_project_is_404(create_env) -> None:
    assert client.delete("/api/projects/gibtesnicht").status_code == 404


def test_restore_refuses_when_the_id_is_taken_again(create_env) -> None:
    """Restoring over a live project would silently merge two directories."""
    _, proj = create_env
    client.post("/api/projects", json={"project_id": "kollision"})
    undo = client.delete("/api/projects/kollision").json()["undo"]
    client.post("/api/projects", json={"project_id": "kollision"})

    assert client.post("/api/projects/restore", json=undo).status_code == 409


def test_the_trash_is_not_listed_as_a_project(create_env) -> None:
    """The trash sits beside data/projects/, never inside it."""
    _, proj = create_env
    client.post("/api/projects", json={"project_id": "verschwunden"})
    client.delete("/api/projects/verschwunden")
    assert ".trash" not in [p.name for p in proj.iterdir()]


@pytest.mark.parametrize("bad", ["../etc", "a/b", ".."])
def test_project_restore_revalidates_the_undo_token(create_env, bad) -> None:
    """An undo token is client-supplied text, not a reason to trust a path."""
    r = client.post(
        "/api/projects/restore", json={"project_id": bad, "trash_name": "x"}
    )
    assert r.status_code == 422
    r = client.post(
        "/api/projects/restore", json={"project_id": "ok", "trash_name": bad}
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Static asset freshness
#
# Starlette's StaticFiles sends ETag and Last-Modified but no Cache-Control.
# Without it a browser falls back to HEURISTIC caching and may reuse app.js
# for a long time without revalidating — so a shipped UI change simply does
# not appear, with no error to explain it. That is how a renamed sidebar label
# kept showing its old text long after the rename was on main.
# ---------------------------------------------------------------------------


def test_static_assets_must_be_revalidated() -> None:
    """no-cache means "revalidate before reuse", not "do not store".

    The ETag makes that a cheap 304 on every unchanged asset, so this costs a
    conditional request rather than a re-download.
    """
    r = client.get("/static/app.js")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-cache"


def test_api_responses_are_not_given_the_static_cache_header() -> None:
    """The header is scoped to /static/, not sprayed over every response."""
    r = client.get("/api/health")
    assert "cache-control" not in {k.lower() for k in r.headers}


def test_the_page_stamps_its_asset_urls_with_the_version() -> None:
    """Belt to Cache-Control's braces.

    Revalidation depends on the browser honouring the header and on nothing in
    between stripping it. A changed URL is a new resource to every cache there
    is, so a released version can never be served from a stale copy.
    """
    body = client.get("/").text
    assert f'/static/app.js?v={__version__}' in body
    assert f'/static/style.css?v={__version__}' in body


def test_the_stamp_does_not_touch_the_file_on_disk() -> None:
    """index.html keeps plain URLs so it stays directly openable."""
    index = (
        Path(__file__).resolve().parents[1]
        / "src/hermes_assistant/webapp/static/index.html"
    )
    assert "?v=" not in index.read_text(encoding="utf-8")
