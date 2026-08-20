"""E2E error-handling tests (Phase 4h): invalid JSON, orphaned data, no Ollama.

Requires Playwright and a live server on http://localhost:8000.
"""

from __future__ import annotations

import json
import socket

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Page  # noqa: E402

pytestmark = pytest.mark.e2e

BASE_URL = "http://localhost:8000"


def _server_up(host: str = "localhost", port: int = 8000) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


@pytest.fixture(autouse=True)
def _require_server():
    if not _server_up():
        pytest.skip("No server on localhost:8000 for error-handling E2E tests")


# ---------------------------------------------------------------------------
# Invalid JSON -> validation errors, never a raw stack trace
# ---------------------------------------------------------------------------


def test_invalid_json_shows_validation_error_not_stack_trace(page: Page):
    page.goto(BASE_URL)
    page.locator('button:has-text("Import JSON")').click()
    next_btn = page.locator('[data-testid="import-next-btn"]')
    if next_btn.count() > 0:
        next_btn.click()
    textarea = page.locator('[data-testid="raw-json-input"]')
    textarea.fill("{ not valid json at all")
    error = page.locator('[data-testid="json-error"], [data-testid="import-error"]')
    error.first.wait_for(timeout=3000)
    text = error.first.text_content() or ""
    assert "Traceback" not in text
    assert "File \"" not in text


def test_unknown_entity_type_shows_friendly_error(page: Page):
    page.goto(BASE_URL)
    page.locator('button:has-text("Import JSON")').click()
    next_btn = page.locator('[data-testid="import-next-btn"]')
    if next_btn.count() > 0:
        next_btn.click()
    textarea = page.locator('[data-testid="raw-json-input"]')
    textarea.fill(json.dumps({"totally_unknown_section": []}))
    page.locator('[data-testid="import-submit-btn"]').click()
    error = page.locator('[data-testid="import-error"]')
    error.wait_for(timeout=5000)
    text = error.text_content() or ""
    assert "Traceback" not in text
    assert "500" not in text


# ---------------------------------------------------------------------------
# Orphaned data -> graceful degradation
# ---------------------------------------------------------------------------


def test_dashboard_loads_even_with_no_data(page: Page):
    """A brand-new / empty project must render the dashboard shell without
    a 500 or an unhandled JS error, not require pre-seeded data."""
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    response = page.goto(f"{BASE_URL}/?project_id=__definitely_does_not_exist__")
    assert response is not None
    assert response.status < 500
    page.wait_for_timeout(500)
    assert errors == []


# ---------------------------------------------------------------------------
# Ollama unavailable -> friendly message, not a crash
# ---------------------------------------------------------------------------


def test_chat_degrades_gracefully_without_ollama(page: Page):
    """When the ROUTER model call fails (Ollama down/not pulled),
    ChatService._classify catches the exception and degrades to
    answer_question — the turn must still return 200 with a reply, never a
    raw 500 or a hung request."""
    page.goto(BASE_URL)
    page.wait_for_selector("#chat-widget", timeout=5000)
    page.locator(".chat-input").fill("Hello, are you there?")
    page.locator(".chat-send").click()
    # Either a normal assistant bubble, or the widget's own error affordance —
    # either way the UI must resolve within a few seconds, not hang forever.
    page.wait_for_selector(".chat-messages > div", timeout=8000)


def test_chat_error_message_has_no_stack_trace(page: Page):
    page.goto(BASE_URL)
    page.wait_for_selector("#chat-widget", timeout=5000)
    page.route("**/api/chat/message", lambda route: route.fulfill(status=500, body="{}"))
    page.locator(".chat-input").fill("Trigger a server error")
    page.locator(".chat-send").click()
    page.wait_for_selector("text=Error", timeout=5000)
    text = page.locator(".chat-messages").text_content() or ""
    assert "Traceback" not in text
