"""FastAPI web server for HERMES Local Assistant dashboard (Phase 4)."""
from __future__ import annotations

import functools
import json as _json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from hermes_assistant import __version__
from hermes_assistant.config import settings
from hermes_assistant.dashboard_html import (
    _FORBIDDEN_FIELDS,
    _FS_RE,
    load_dashboard_data,
)

logger = logging.getLogger(__name__)

# Matches field names that begin with internal_ or confidential_ (any suffix).
_INTERNAL_FIELD_RE = re.compile(
    r'"(internal_[^"]*|confidential_[^"]*)\s*"', re.IGNORECASE
)
# RFC-5322-ish email detector for values that must not appear in API output.
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

_STATIC_DIR = Path(__file__).resolve().parent / "static"

# CSP: 'self' + any HTTPS source for scripts/styles (allows CDN-hosted Vue 3 /
# Tailwind without hard-coding external hostnames in the Python source).
# 'unsafe-inline' is required by Tailwind's CDN runtime style injection.
# This tool is locally-hosted and company-network only; no auth gate exists,
# so a scheme-only allowlist (https:) is an acceptable trade-off for simplicity.
_CSP = (
    "default-src 'none'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https:; "
    "style-src 'self' 'unsafe-inline' https:; "
    "img-src 'self' data:; "
    "connect-src 'self'"
)


class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject hardened security headers on every response."""

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response


def _redact_user_authored(obj: Any) -> Any:
    """Return a copy of *obj* with user-authored message content blanked.

    User-role chat messages contain text the user typed themselves — their own
    email address, a filesystem path they mentioned, etc. That is not a
    confidentiality *leak* from the store or the model, so it must be excluded
    from the email/path PII scan (H1). Field-name and internal_*/confidential_*
    checks still run against the full, unredacted payload.

    The walk is structural: any dict with ``role == "user"`` and a ``content``
    key has that content blanked; all other values are preserved.
    """
    if isinstance(obj, dict):
        if obj.get("role") == "user" and "content" in obj:
            redacted = {k: _redact_user_authored(v) for k, v in obj.items()}
            redacted["content"] = ""
            return redacted
        return {k: _redact_user_authored(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_user_authored(v) for v in obj]
    return obj


def _validate_safe_json(json_str: str, pii_json_str: str | None = None) -> list[str]:
    """Return a list of confidentiality violations found in the serialised JSON.

    An empty list means the payload is clean and safe to send to clients.
    Checks performed:
    - Exact forbidden field names (raw_notes, evidence_quote, …)
    - Field names matching internal_* or confidential_* patterns
    - Absolute filesystem paths in values
    - Email addresses in values

    ``pii_json_str`` (H1): when provided, the value-based PII scans (absolute
    filesystem paths and email addresses) run against this string instead of
    ``json_str``. Callers pass a copy with user-authored message content
    removed so a user's own email/path in a chat message does not trip the
    guard. Field-name checks always run against the full ``json_str``.
    """
    structural, content = _classify_violations(json_str, pii_json_str)
    return structural + content


def _classify_violations(
    json_str: str, pii_json_str: str | None = None
) -> tuple[list[str], list[str]]:
    """Split confidentiality violations into (structural, content).

    The distinction decides whether a response can be salvaged:

    - **Structural** — a forbidden or internal_*/confidential_* *field name*
      reached the serialiser. That is a programming error: a view model is
      exposing something it never should. It must fail loudly.
    - **Content** — an email address or absolute path appears in a *value*.
      That is untrusted data, not a bug, and it arrives routinely in imported
      material drawn from meeting minutes. Failing the whole response for it
      lets one imported row disable a screen permanently.
    """
    structural: list[str] = []
    content: list[str] = []
    lower = json_str.lower()
    pii_source = json_str if pii_json_str is None else pii_json_str

    # Exact forbidden field names from the shared allowlist
    for field in _FORBIDDEN_FIELDS:
        if f'"{field}"' in lower:
            structural.append(f"Forbidden field {field!r} found in API response")

    # Pattern-matched forbidden field name prefixes
    if _INTERNAL_FIELD_RE.search(json_str):
        structural.append(
            "Field matching internal_* or confidential_* pattern found in API response"
        )

    # Absolute filesystem paths (user-authored content excluded via pii_source)
    if _FS_RE.search(pii_source):
        content.append("Absolute filesystem path found in API response")

    # Email addresses (user-authored content excluded via pii_source)
    if _EMAIL_RE.search(pii_source):
        content.append("Email address found in API response")

    return structural, content


# Replacements carry no JSON-special characters, so substituting them inside a
# serialised document cannot break its syntax.
_PII_PLACEHOLDERS = (("[E-Mail entfernt]", "email"), ("[Pfad entfernt]", "path"))


def _redact_pii(json_str: str) -> str:
    """Blank emails and absolute paths in a serialised JSON document."""
    redacted = _EMAIL_RE.sub("[E-Mail entfernt]", json_str)
    return _FS_RE.sub("[Pfad entfernt]", redacted)


def confidentiality_guard(func):  # type: ignore[no-untyped-def]
    """Decorator: validate all endpoint responses for confidential data.

    Applied to any endpoint that returns a plain ``dict`` (FastAPI auto-JSON
    responses).  Endpoints that return an explicit ``Response`` object handle
    validation inline (e.g. ``/api/dashboard``).
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
        response = await func(*args, **kwargs)
        if isinstance(response, dict):
            violations = _validate_safe_json(
                _json.dumps(response),
                _json.dumps(_redact_user_authored(response)),
            )
            if violations:
                # H2: log violation detail server-side only; send generic message to client.
                logger.warning(
                    "Confidentiality guard triggered on %s: %s",
                    func.__name__,
                    "; ".join(violations),
                )
                raise HTTPException(status_code=500, detail="Internal error")
        return response

    return wrapper


app = FastAPI(
    title="HERMES Dashboard API",
    description=(
        "Locally-hosted JSON API for the HERMES project management dashboard. "
        "All responses are validated by the confidentiality guard before delivery."
    ),
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

app.add_middleware(_SecurityHeadersMiddleware)

# Serve static assets (JS, CSS, fonts) from the sibling static/ directory.
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# Mount the chat assistant API (Phase 5). Imported here — after ``app`` and
# ``confidentiality_guard`` exist — because ``chat_api`` imports the guard from
# this module, and the router must be registered before the catch-all SPA route
# below so ``/api/chat/*`` paths are not swallowed by the client-side fallback.
from hermes_assistant.webapp import chat_api  # noqa: E402

app.include_router(chat_api.router)


@app.get("/api/health")
@confidentiality_guard
async def health() -> dict[str, str]:
    """Health check — always returns 200 OK with current timestamp.

    Also carries the running ``version`` so the dashboard can display it
    without hard-coding a version string in the frontend. The single source
    of truth is ``hermes_assistant.__version__``; ``test_version_matches_
    pyproject`` keeps it in step with the packaging metadata.
    """
    return {
        "status": "ok",
        "version": __version__,
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


@app.get("/api/dashboard")
async def dashboard(project_id: str | None = Query(default=None)) -> Response:
    """Return DashboardData as JSON.

    Confidentiality guards are applied before the response is sent:
    forbidden field names (raw_notes, evidence_quote, etc.) and absolute
    filesystem paths will cause a 500 error rather than data leakage.
    """
    try:
        data = load_dashboard_data(project_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Data load failed: {exc}"
        ) from exc

    json_str = data.model_dump_json()
    structural, content = _classify_violations(json_str)

    if structural:
        # A view model is exposing a field it never should — a code bug.
        # H2: log detail server-side; send generic message to client.
        logger.warning(
            "Confidentiality guard triggered on dashboard: %s", "; ".join(structural)
        )
        raise HTTPException(status_code=500, detail="Internal error")

    if content:
        # An email or path in imported content must never leave the process,
        # but it must not take the dashboard down either: rows are stored
        # verbatim, so failing here would make the screen unreachable on every
        # request until somebody edited the database by hand. Redact and serve.
        # The importer already scrubs new rows; this covers anything stored
        # before that existed, or written by another path.
        logger.warning(
            "Redacted content from dashboard response: %s", "; ".join(content)
        )
        json_str = _redact_pii(json_str)

    return Response(content=json_str, media_type="application/json")


@app.get("/api/refresh")
async def refresh(project_id: str | None = Query(default=None)) -> Response:
    """Trigger a fresh data load from disk and return updated DashboardData."""
    return await dashboard(project_id)


_TASK_STATUSES = ("open", "closed", "blocked")

# An owner is a role or a name. Anything longer is a sentence that has wandered
# into the wrong field, and it would be rendered on every row of the plan.
_MAX_OWNER_LEN = 80

# A title is a headline, not a paragraph. The cap is generous enough for a real
# one and short enough that a pasted wall of text is rejected rather than
# rendered across every view that lists it.
_MAX_TITLE_LEN = 200
_MAX_DESCRIPTION_LEN = 2000

_PRIORITIES = ("low", "medium", "high", "blocker")
# "pendenz" is excluded on purpose: that is what POST /api/todos creates,
# and offering two routes for one thing invites them to drift.
# "assumption" holds internal planning notes the dashboard never renders.
_CREATABLE_NODE_KINDS = ("task", "deliverable", "milestone")


def _clean_text(value: Any, field: str, limit: int, *, required: bool = False) -> str:
    """Validate and redact one free-text field from a create request.

    Everything typed here is stored verbatim and rendered on the dashboard, so
    it goes through the same redaction the importer applies. Hand-entered text
    is *more* likely to carry an email address than imported text, not less —
    somebody pasting "chase up with a.muster@example.com" would otherwise make
    every dashboard response 500 until the row was edited out of the database
    by hand.
    """
    from hermes_assistant.webapp.import_json import _redact_unsafe_text

    if value is None:
        value = ""
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"{field} must be a string")
    text = value.strip()
    if required and not text:
        raise HTTPException(status_code=422, detail=f"{field} is required")
    if len(text) > limit:
        raise HTTPException(
            status_code=422, detail=f"{field} must be at most {limit} characters"
        )
    cleaned, _ = _redact_unsafe_text(text)
    return cleaned


def _json_body(raw: bytes) -> dict[str, Any]:
    try:
        body = _json.loads(raw or b"{}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Body is not valid JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Body must be a JSON object")
    return body


@app.post("/api/todos")
@confidentiality_guard
async def create_todo(request: Request) -> dict[str, Any]:
    """Create one to-do by hand.

    Everything on the dashboard arrived by import until now, which made it
    read-only for anything that came up between exports — the exact moments a
    to-do is born. A hand-created item is a ``Pendenz`` with
    ``source="manual"``, so it is the same shape as an imported one and needs
    no separate store or view.

    Body: ``{"title", "owner"?, "priority"?, "due_date"?, "description"?}``.
    """
    from hermes_assistant.tasks.pendenzen import Pendenz, PendenzSource
    from hermes_assistant.tasks.store import TaskStore
    from hermes_assistant.webapp.import_json import _parse_due

    body = _json_body(await request.body())

    title = _clean_text(body.get("title"), "title", _MAX_TITLE_LEN, required=True)
    owner = _clean_text(body.get("owner"), "owner", _MAX_OWNER_LEN)
    description = _clean_text(
        body.get("description"), "description", _MAX_DESCRIPTION_LEN
    )

    priority = body.get("priority", "medium")
    if priority not in _PRIORITIES:
        raise HTTPException(
            status_code=422, detail=f"priority must be one of {', '.join(_PRIORITIES)}"
        )

    raw_due = body.get("due_date")
    due = _parse_due(raw_due)
    # A date that was supplied but unusable is a mistake worth reporting: a
    # silently dropped deadline is worse than a rejected form.
    if raw_due and due is None:
        raise HTTPException(status_code=422, detail="due_date must be YYYY-MM-DD")

    store = TaskStore(settings.tasks_db_path)
    try:
        new_id = store.create(
            Pendenz(
                id="",
                title=title,
                description=description,
                owner=owner or None,
                priority=priority,
                due_date=due,
                source=PendenzSource.manual,
            )
        )
    finally:
        store.close()
    return {"id": new_id, "title": title, "kind": "todo"}


@app.post("/api/tasks")
@confidentiality_guard
async def create_task(request: Request) -> dict[str, Any]:
    """Create one work-breakdown node by hand.

    Body: ``{"title", "node_kind"?, "parent_id"?, "owner"?, "status"?}``.
    """
    from hermes_assistant.tasks.model import Task
    from hermes_assistant.tasks.store import TaskStore

    body = _json_body(await request.body())

    title = _clean_text(body.get("title"), "title", _MAX_TITLE_LEN, required=True)
    owner = _clean_text(body.get("owner"), "owner", _MAX_OWNER_LEN)

    node_kind = body.get("node_kind", "task")
    if node_kind not in _CREATABLE_NODE_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"node_kind must be one of {', '.join(_CREATABLE_NODE_KINDS)}",
        )
    status = body.get("status", "open")
    if status not in _TASK_STATUSES:
        raise HTTPException(
            status_code=422, detail=f"status must be one of {', '.join(_TASK_STATUSES)}"
        )

    parent_id = body.get("parent_id") or None
    if parent_id is not None and not isinstance(parent_id, str):
        raise HTTPException(status_code=422, detail="parent_id must be a string")

    store = TaskStore(settings.tasks_db_path)
    try:
        # A parent that does not exist would leave the node orphaned in the
        # tree — visible on the board but absent from the WBS.
        if parent_id is not None and store.get(parent_id) is None:
            raise HTTPException(status_code=404, detail="Parent task not found")
        new_id = store.create(
            Task(
                id="",
                title=title,
                owner=owner or None,
                status=status,
                node_kind=node_kind,
                parent_id=parent_id,
            )
        )
    finally:
        store.close()
    return {"id": new_id, "title": title, "kind": "task"}


@app.post("/api/projects")
@confidentiality_guard
async def create_project(request: Request) -> dict[str, Any]:
    """Create an empty project directory.

    Body: ``{"project_id"}``. The id becomes a directory name, so it goes
    through the importer's own path guard rather than a second copy.
    """
    from hermes_assistant.webapp.import_json import _is_safe_path_segment

    body = _json_body(await request.body())
    project_id = body.get("project_id")
    if not isinstance(project_id, str) or not project_id.strip():
        raise HTTPException(status_code=422, detail="project_id is required")
    project_id = project_id.strip()
    if not _is_safe_path_segment(project_id):
        raise HTTPException(
            status_code=422,
            detail="project_id must be a single safe directory name "
            "(letters, digits, . _ -)",
        )

    proj_dir = Path(settings.projects_path) / project_id
    if proj_dir.exists():
        raise HTTPException(status_code=409, detail="Project already exists")
    proj_dir.mkdir(parents=True)
    return {"project_id": project_id, "kind": "project"}



@app.post("/api/schedule/{project_id}/items/{item_id}/owner")
@confidentiality_guard
async def set_schedule_item_owner(
    project_id: str, item_id: str, request: Request
) -> dict[str, Any]:
    """Reassign one dated obligation to somebody else.

    A swept plan is only as good as its owners, and those are the field an
    import gets wrong most often — a protocol names "IT", the plan means a
    person. Fixing that had meant re-running the whole export.

    Body: ``{"owner": "<role or name>"}``; an empty string clears it.
    """
    from hermes_assistant.scheduling.model import Schedule

    try:
        body = _json.loads(await request.body() or b"{}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Body is not valid JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Body must be a JSON object")

    owner = body.get("owner", "")
    if not isinstance(owner, str):
        raise HTTPException(status_code=422, detail="owner must be a string")
    owner = owner.strip()
    if len(owner) > _MAX_OWNER_LEN:
        raise HTTPException(
            status_code=422, detail=f"owner must be at most {_MAX_OWNER_LEN} characters"
        )
    # Whatever is written here is rendered on every row of the plan and shipped
    # in every dashboard response, so it goes through the same redaction the
    # importer applies. Without it one pasted email address would 500 the
    # dashboard permanently.
    from hermes_assistant.webapp.import_json import _redact_unsafe_text

    owner, redactions = _redact_unsafe_text(owner)

    # The id comes from the URL and is used to build a path, so it must not be
    # able to climb out of the projects root.
    # Reuses the importer's guard rather than a second copy: two path checks
    # that can drift is exactly how a traversal hole opens.
    from hermes_assistant.webapp.import_json import _is_safe_path_segment

    if not _is_safe_path_segment(project_id):
        raise HTTPException(status_code=422, detail="Invalid project_id")

    sched_file = Path(settings.projects_path) / project_id / "schedule.json"
    if not sched_file.is_file():
        raise HTTPException(status_code=404, detail="Project has no schedule")

    try:
        schedule = Schedule.model_validate_json(sched_file.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Internal error") from exc

    for item in schedule.items:
        if item.item_id == item_id:
            item.owner = owner or None
            break
    else:
        raise HTTPException(status_code=404, detail="Item not found")

    sched_file.write_text(schedule.model_dump_json(indent=2), encoding="utf-8")
    return {
        "project_id": project_id,
        "item_id": item_id,
        "owner": owner,
        "redacted": redactions,
    }


@app.post("/api/tasks/{task_id}/status")
@confidentiality_guard
async def set_task_status(task_id: str, request: Request) -> dict[str, Any]:
    """Move a task between the kanban columns.

    ``TaskStore.update()`` has always been able to do this — and logs every
    change as a ``TaskUpdate`` for the audit trail — but nothing reachable
    from the browser ever called it, so the board was read-only: cards could
    be opened and read, never moved. This is that missing route.

    Body: ``{"status": "open" | "closed" | "blocked"}``.
    """
    from hermes_assistant.tasks.store import TaskStore

    try:
        body = _json.loads(await request.body() or b"{}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Body is not valid JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Body must be a JSON object")

    status = body.get("status")
    if status not in _TASK_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"status must be one of {', '.join(_TASK_STATUSES)}",
        )

    store = TaskStore(settings.tasks_db_path)
    try:
        task = store.update(task_id, changed_by="dashboard", status=status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc

    # Deliberately narrow: the board only needs to re-place the card. Echoing
    # the whole task would put description and metadata — neither filtered by
    # the dashboard's field allowlist — on a response that has no need of it.
    return {
        "id": task.id,
        "status": task.status,
        "wbs_number": task.wbs_number,
        "updated_at": task.updated_at.isoformat(),
    }


def _get_import_paths() -> dict[str, str]:
    """Return database path kwargs for import_payload. Patched in tests."""
    data = Path(settings.data_dir)
    return {
        "risks_db": str(data / "risks.db"),
        "plans_db": str(data / "plans.db"),
        "tasks_db": settings.tasks_db_path,
        "projects_root": settings.projects_path,
    }


@app.post("/api/import/json")
async def import_json(request: Request) -> Response:
    """Import JSON data (risks, plans, pendenzen, projects).

    Accepts:
    - ``Content-Type: application/json`` — body is the import payload dict.
    - ``Content-Type: multipart/form-data`` — field ``file`` (UploadFile)
      or field ``raw_json`` (text string).

    Returns an ImportResult JSON object with created/updated/skipped counts
    and per-item detail.  Validation errors produce HTTP 422; an oversized
    payload produces HTTP 413.
    """
    from hermes_assistant.webapp.import_json import (
        MAX_IMPORT_BYTES,
        ImportResult,
        import_payload,
        loads_forgiving,
        validate_import_payload,
    )

    # Repairs applied to malformed-but-salvageable Copilot output; surfaced in
    # the result so a sloppy export is visible rather than silently accepted.
    json_repairs: list[str] = []

    content_type = request.headers.get("content-type", "")

    # ── Parse input ───────────────────────────────────────────────────────
    try:
        if "multipart/form-data" in content_type:
            form = await request.form()
            raw_file = form.get("file")
            raw_text = form.get("raw_json")
            if raw_file is not None:
                content = await raw_file.read()  # type: ignore[union-attr]
                if len(content) > MAX_IMPORT_BYTES:
                    raise HTTPException(
                        status_code=413, detail="File exceeds 10 MB limit"
                    )
                payload, json_repairs = loads_forgiving(content)
            elif raw_text is not None:
                payload, json_repairs = loads_forgiving(str(raw_text))
            else:
                raise HTTPException(
                    status_code=422,
                    detail="No 'file' or 'raw_json' field in form data",
                )
        else:
            body = await request.body()
            if len(body) > MAX_IMPORT_BYTES:
                raise HTTPException(
                    status_code=413, detail="Payload exceeds 10 MB limit"
                )
            if not body:
                raise HTTPException(status_code=422, detail="Empty request body")
            payload, json_repairs = loads_forgiving(body)
    except HTTPException:
        raise
    except _json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=422, detail=f"Invalid JSON: {exc}"
        ) from exc

    # ── Adapt schema (Copilot → native) ──────────────────────────────────
    from hermes_assistant.webapp.import_adapters import adapt_payload

    try:
        payload = adapt_payload(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Schema adaptation failed: {exc}",
        ) from exc
    skipped_sections: list[str] = payload.pop("_skipped_sections", [])

    # ── Validate structure ────────────────────────────────────────────────
    structure_errors = validate_import_payload(payload)
    if structure_errors:
        raise HTTPException(status_code=422, detail={"errors": structure_errors})

    # ── Execute import ────────────────────────────────────────────────────
    result: ImportResult = import_payload(payload, **_get_import_paths())
    # Surface adapter-skipped sections (e.g. open_assumptions, decisions) as
    # informational errors so callers know data was not silently dropped.
    for sec in skipped_sections:
        result.errors.append(
            f"Section {sec!r} is not supported by the importer and was skipped"
        )
    for repair in json_repairs:
        result.errors.append(f"JSON repariert: {repair}")
    json_str = result.model_dump_json()
    violations = _validate_safe_json(json_str)
    if violations:
        # H2: log detail server-side; send generic message to client.
        logger.warning(
            "Confidentiality guard triggered on import: %s", "; ".join(violations)
        )
        raise HTTPException(status_code=500, detail="Internal error")
    return Response(content=json_str, media_type="application/json")


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str) -> Response:
    """Serve index.html for all non-API paths (SPA client-side routing)."""
    index_path = _STATIC_DIR / "index.html"
    if not index_path.is_file():
        raise HTTPException(
            status_code=503,
            detail=(
                "UI not found. Ensure the static/ directory exists next to server.py. "
                "Run: bash scripts/start-web.sh"
            ),
        )
    return Response(
        content=index_path.read_text(encoding="utf-8"),
        media_type="text/html",
    )
