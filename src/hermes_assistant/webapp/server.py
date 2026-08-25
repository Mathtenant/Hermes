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
    violations: list[str] = []
    lower = json_str.lower()
    pii_source = json_str if pii_json_str is None else pii_json_str

    # Exact forbidden field names from the shared allowlist
    for field in _FORBIDDEN_FIELDS:
        if f'"{field}"' in lower:
            violations.append(f"Forbidden field {field!r} found in API response")

    # Pattern-matched forbidden field name prefixes
    if _INTERNAL_FIELD_RE.search(json_str):
        violations.append(
            "Field matching internal_* or confidential_* pattern found in API response"
        )

    # Absolute filesystem paths (user-authored content excluded via pii_source)
    if _FS_RE.search(pii_source):
        violations.append("Absolute filesystem path found in API response")

    # Email addresses (user-authored content excluded via pii_source)
    if _EMAIL_RE.search(pii_source):
        violations.append("Email address found in API response")

    return violations


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
    violations = _validate_safe_json(json_str)
    if violations:
        # H2: log detail server-side; send generic message to client.
        logger.warning(
            "Confidentiality guard triggered on dashboard: %s", "; ".join(violations)
        )
        raise HTTPException(status_code=500, detail="Internal error")
    return Response(content=json_str, media_type="application/json")


@app.get("/api/refresh")
async def refresh(project_id: str | None = Query(default=None)) -> Response:
    """Trigger a fresh data load from disk and return updated DashboardData."""
    return await dashboard(project_id)


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
        validate_import_payload,
    )

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
                payload = _json.loads(content)
            elif raw_text is not None:
                payload = _json.loads(str(raw_text))
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
            payload = _json.loads(body)
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
