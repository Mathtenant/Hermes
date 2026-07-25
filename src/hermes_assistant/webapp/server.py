"""FastAPI web server for HERMES Local Assistant dashboard (Phase 4)."""
from __future__ import annotations

import functools
import json as _json
import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from hermes_assistant.dashboard_html import (
    _FORBIDDEN_FIELDS,
    _FS_RE,
    load_dashboard_data,
)

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


def _validate_safe_json(json_str: str) -> list[str]:
    """Return a list of confidentiality violations found in the serialised JSON.

    An empty list means the payload is clean and safe to send to clients.
    Checks performed:
    - Exact forbidden field names (raw_notes, evidence_quote, …)
    - Field names matching internal_* or confidential_* patterns
    - Absolute filesystem paths in values
    - Email addresses in values
    """
    violations: list[str] = []
    lower = json_str.lower()

    # Exact forbidden field names from the shared allowlist
    for field in _FORBIDDEN_FIELDS:
        if f'"{field}"' in lower:
            violations.append(f"Forbidden field {field!r} found in API response")

    # Pattern-matched forbidden field name prefixes
    if _INTERNAL_FIELD_RE.search(json_str):
        violations.append(
            "Field matching internal_* or confidential_* pattern found in API response"
        )

    # Absolute filesystem paths
    if _FS_RE.search(json_str):
        violations.append("Absolute filesystem path found in API response")

    # Email addresses
    if _EMAIL_RE.search(json_str):
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
            violations = _validate_safe_json(_json.dumps(response))
            if violations:
                raise HTTPException(
                    status_code=500,
                    detail=f"Confidentiality guard triggered: {'; '.join(violations)}",
                )
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


@app.get("/api/health")
@confidentiality_guard
async def health() -> dict[str, str]:
    """Health check — always returns 200 OK with current timestamp."""
    return {
        "status": "ok",
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
        raise HTTPException(
            status_code=500,
            detail=f"Confidentiality guard triggered: {'; '.join(violations)}",
        )
    return Response(content=json_str, media_type="application/json")


@app.get("/api/refresh")
async def refresh(project_id: str | None = Query(default=None)) -> Response:
    """Trigger a fresh data load from disk and return updated DashboardData."""
    return await dashboard(project_id)


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
