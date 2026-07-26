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


@pytest.mark.asyncio
async def test_confidentiality_guard_passes_clean_dict() -> None:
    @confidentiality_guard
    async def endpoint() -> dict[str, str]:
        return {"status": "ok"}

    result = await endpoint()
    assert result == {"status": "ok"}


@pytest.mark.asyncio
async def test_confidentiality_guard_raises_500_on_violation() -> None:
    @confidentiality_guard
    async def endpoint() -> dict[str, str]:
        return {"raw_notes": "should never leave the server"}

    with pytest.raises(HTTPException) as exc_info:
        await endpoint()
    assert exc_info.value.status_code == 500
    assert "confidentiality" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_confidentiality_guard_reports_all_violations() -> None:
    @confidentiality_guard
    async def endpoint() -> dict[str, str]:
        return {"raw_notes": "x", "internal_budget": "y"}

    with pytest.raises(HTTPException) as exc_info:
        await endpoint()
    detail = exc_info.value.detail.lower()
    assert "raw_notes" in detail
    assert "internal_" in detail


@pytest.mark.asyncio
async def test_confidentiality_guard_ignores_non_dict_responses() -> None:
    """Endpoints returning a Response object (not a dict) are not re-validated
    here — they're expected to call _validate_safe_json explicitly (as
    /api/dashboard does)."""

    @confidentiality_guard
    async def endpoint() -> str:
        return "raw_notes"  # a bare string is not JSON-validated by the decorator

    result = await endpoint()
    assert result == "raw_notes"
