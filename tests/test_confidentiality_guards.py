"""Unit tests for the API confidentiality guard (webapp/server.py).

Complements ``tests/test_webapp_endpoints.py`` (which exercises the guard
end-to-end through ``/api/dashboard``) with focused unit-level coverage of
``_validate_safe_json`` and the ``@confidentiality_guard`` decorator itself.
"""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from hermes_assistant.webapp.server import _validate_safe_json, confidentiality_guard


def _await(coro):
    """Drive *coro* to completion on a private loop in its own thread.

    These tests were ``@pytest.mark.asyncio`` coroutines, which fail with
    "Runner.run() cannot be called from a running event loop" whenever the
    session also collects the Playwright E2E tests: Playwright's sync API keeps
    a greenlet-driven loop running in the main thread, and pytest-asyncio
    cannot start another one there. The suite therefore passed or failed
    depending on which files were run together — the kind of flakiness that
    teaches people to ignore red.

    Running the coroutine on a dedicated thread makes these tests independent
    of whatever the main thread's loop is doing.
    """
    import asyncio
    import threading

    box: dict[str, object] = {}

    def runner() -> None:
        loop = asyncio.new_event_loop()
        try:
            box["value"] = loop.run_until_complete(coro)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller
            box["error"] = exc
        finally:
            loop.close()

    thread = threading.Thread(target=runner)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box["value"]

# ---------------------------------------------------------------------------
# _validate_safe_json — forbidden field names
# ---------------------------------------------------------------------------


def test_validate_safe_json_blocks_raw_notes() -> None:
    violations = _validate_safe_json(json.dumps({"raw_notes": "leaked internal note"}))
    assert any("raw_notes" in v for v in violations)


def test_validate_safe_json_blocks_evidence_quote() -> None:
    violations = _validate_safe_json(json.dumps({"evidence_quote": "verbatim quote"}))
    assert any("evidence_quote" in v for v in violations)


def test_validate_safe_json_blocks_rationale() -> None:
    violations = _validate_safe_json(json.dumps({"rationale": "internal reasoning"}))
    assert any("rationale" in v for v in violations)


def test_validate_safe_json_blocks_fix_suggestion() -> None:
    violations = _validate_safe_json(json.dumps({"fix_suggestion": "do X instead"}))
    assert any("fix_suggestion" in v for v in violations)


def test_validate_safe_json_blocks_open_assumptions() -> None:
    violations = _validate_safe_json(json.dumps({"open_assumptions": "assumes Y"}))
    assert any("open_assumptions" in v for v in violations)


def test_validate_safe_json_blocks_assumptions() -> None:
    violations = _validate_safe_json(json.dumps({"assumptions": ["A", "B"]}))
    assert any("assumptions" in v for v in violations)


# ---------------------------------------------------------------------------
# _validate_safe_json — pattern-matched field name prefixes
# ---------------------------------------------------------------------------


def test_validate_safe_json_detects_internal_star_pattern() -> None:
    violations = _validate_safe_json(json.dumps({"internal_budget": 50000}))
    assert any("internal_" in v for v in violations)


def test_validate_safe_json_detects_confidential_star_pattern() -> None:
    violations = _validate_safe_json(json.dumps({"confidential_client_name": "Acme"}))
    assert any("confidential_" in v for v in violations)


# ---------------------------------------------------------------------------
# _validate_safe_json — email / filesystem path detection
# ---------------------------------------------------------------------------


def test_validate_safe_json_blocks_email_address() -> None:
    violations = _validate_safe_json(json.dumps({"contact": "alice@example.com"}))
    assert any("email" in v.lower() for v in violations)


def test_validate_safe_json_blocks_windows_path() -> None:
    violations = _validate_safe_json(json.dumps({"path": r"C:\\Users\\alice\\secrets"}))
    assert any("filesystem path" in v.lower() for v in violations)


def test_validate_safe_json_blocks_private_tmp_path() -> None:
    violations = _validate_safe_json(json.dumps({"path": "/private/tmp/leak.txt"}))
    assert any("filesystem path" in v.lower() for v in violations)


def test_validate_safe_json_clean_payload_has_no_violations() -> None:
    clean = json.dumps({"title": "Phase 1 kickoff", "status": "open", "count": 3})
    assert _validate_safe_json(clean) == []


# ---------------------------------------------------------------------------
# @confidentiality_guard decorator
# ---------------------------------------------------------------------------


def test_confidentiality_guard_passes_clean_dict() -> None:
    @confidentiality_guard
    async def endpoint() -> dict[str, str]:
        return {"status": "ok"}

    assert _await(endpoint()) == {"status": "ok"}


def test_confidentiality_guard_raises_500_on_violation() -> None:
    @confidentiality_guard
    async def endpoint() -> dict[str, str]:
        return {"raw_notes": "should never leave the server"}

    with pytest.raises(HTTPException) as exc_info:
        _await(endpoint())
    assert exc_info.value.status_code == 500
    # H2: detail must be generic — forbidden field names must not be disclosed to clients.
    assert exc_info.value.detail == "Internal error"


def test_confidentiality_guard_detail_is_generic_not_violations() -> None:
    """H2: the HTTP error detail must never expose which fields triggered the guard."""

    @confidentiality_guard
    async def endpoint() -> dict[str, str]:
        return {"raw_notes": "x", "internal_budget": "y"}

    with pytest.raises(HTTPException) as exc_info:
        _await(endpoint())
    assert exc_info.value.status_code == 500
    detail = exc_info.value.detail.lower()
    # Violation field names must NOT appear in the client-facing error.
    assert "raw_notes" not in detail
    assert "internal_" not in detail
    assert "internal_budget" not in detail


def test_confidentiality_guard_ignores_non_dict_responses() -> None:
    """Endpoints returning a Response object (not a dict) are not re-validated
    here — they're expected to call _validate_safe_json explicitly (as
    /api/dashboard does)."""

    @confidentiality_guard
    async def endpoint() -> str:
        return "raw_notes"  # a bare string is not JSON-validated by the decorator

    assert _await(endpoint()) == "raw_notes"


# ---------------------------------------------------------------------------
# Risk Registry — owner email must not leak via dashboard
# ---------------------------------------------------------------------------


def test_risk_owner_email_excluded_from_dashboard_response() -> None:
    """A risk with an owner email must not expose that email in the dashboard response.

    RiskRow omits 'owner', so export_public() results stripped to safe fields
    must pass _validate_safe_json without an email violation.
    """
    from hermes_assistant.dashboard_html import DashboardData, RiskRow

    row = RiskRow(
        id="abc123",
        title="Budget overrun",
        severity="high",
        likelihood=3,
        status="open",
        score=9,
        updated_at="2026-01-01T00:00:00Z",
    )
    data = DashboardData(generated_at="2026-01-01T00:00:00Z", risks=[row])
    json_str = data.model_dump_json()
    # No email should appear in the serialised payload
    assert "@" not in json_str
    violations = _validate_safe_json(json_str)
    assert not any("email" in v.lower() for v in violations)
