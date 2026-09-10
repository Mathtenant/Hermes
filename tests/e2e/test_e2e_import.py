"""E2E browser tests for the two-step Copilot JSON import wizard (Phase 4e).

Complements ``test_json_import_ui.py`` (which drives the paste/upload +
submit flow directly) with the step-1 "Copilot prompt" screen and the M2
re-import idempotency guarantee observed end-to-end through the dashboard's
risk counter.

Requires Playwright and a live server on http://localhost:8000.
"""

from __future__ import annotations

import json
import socket
import uuid

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Page  # noqa: E402

from tests.e2e.hidden_screens import risk_count, risk_titles  # noqa: E402

pytestmark = pytest.mark.e2e

BASE_URL = "http://localhost:8000"


def _server_up(host: str = "localhost", port: int = 8000) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


@pytest.fixture(autouse=True)
def _require_server():
    if not _server_up():
        pytest.skip("No server on localhost:8000 for import E2E tests")


@pytest.fixture
def import_modal(page: Page) -> Page:
    page.goto(BASE_URL)
    page.locator('button:has-text("Import JSON")').click()
    page.wait_for_selector('[data-testid="json-import-modal"]', timeout=5000)
    return page


# ---------------------------------------------------------------------------
# Step 1 — Copilot prompt visible
# ---------------------------------------------------------------------------


def test_copilot_prompt_text_visible(import_modal: Page):
    prompt = import_modal.locator('[data-testid="copilot-prompt-text"]')
    assert prompt.is_visible()
    assert prompt.text_content().strip() != ""


def test_copy_prompt_button_present(import_modal: Page):
    assert import_modal.locator('[data-testid="copy-prompt-btn"]').is_visible()


def test_advance_to_paste_step(import_modal: Page):
    next_btn = import_modal.locator('[data-testid="import-next-btn"]')
    if next_btn.count() == 0:
        pytest.skip("Wizard already on the paste/upload step in this build.")
    next_btn.click()
    assert import_modal.locator('[data-testid="raw-json-input"]').is_visible()


# ---------------------------------------------------------------------------
# Paste JSON -> inline validation errors
# ---------------------------------------------------------------------------


def test_paste_invalid_json_shows_inline_error(import_modal: Page):
    next_btn = import_modal.locator('[data-testid="import-next-btn"]')
    if next_btn.count() > 0:
        next_btn.click()
    textarea = import_modal.locator('[data-testid="raw-json-input"]')
    textarea.fill("{ this is not valid json")
    error = import_modal.locator('[data-testid="json-error"], [data-testid="import-error"]')
    error.first.wait_for(timeout=3000)
    assert error.first.is_visible()


def test_paste_missing_entity_type_shows_error_on_submit(import_modal: Page):
    next_btn = import_modal.locator('[data-testid="import-next-btn"]')
    if next_btn.count() > 0:
        next_btn.click()
    textarea = import_modal.locator('[data-testid="raw-json-input"]')
    textarea.fill(json.dumps({"unknown_key": []}))
    import_modal.locator('[data-testid="import-submit-btn"]').click()
    error = import_modal.locator('[data-testid="import-error"]')
    error.wait_for(timeout=5000)
    assert error.is_visible()


# ---------------------------------------------------------------------------
# Success -> UIs populated
# ---------------------------------------------------------------------------


def test_successful_import_populates_risk_count(import_modal: Page):
    """The register used to be read off the page; the Risks screen is hidden,
    so it is read off ``/api/dashboard`` — the same data, one layer down.

    Comparing counts alone would pass on any import at all, so the title is
    checked too: it is made unique per run because an id-less risk is a new
    row every time, and a repeat run must not be able to satisfy this from a
    previous one's leftovers.
    """
    title = f"E2E import risk {uuid.uuid4().hex[:8]}"
    before = risk_count(import_modal, BASE_URL)

    next_btn = import_modal.locator('[data-testid="import-next-btn"]')
    if next_btn.count() > 0:
        next_btn.click()
    textarea = import_modal.locator('[data-testid="raw-json-input"]')
    textarea.fill(json.dumps({"risks": [{"title": title}]}))
    import_modal.locator('[data-testid="import-submit-btn"]').click()
    import_modal.locator("text=Successfully imported").wait_for(timeout=5000)

    assert risk_count(import_modal, BASE_URL) > before
    assert title in risk_titles(import_modal, BASE_URL)


# ---------------------------------------------------------------------------
# M2 — re-import same JSON -> no duplicates
# ---------------------------------------------------------------------------


def test_reimport_same_json_does_not_duplicate(page: Page):
    payload = json.dumps(
        {"risks": [{"id": "e2e-fixed-id", "title": "Idempotent risk"}]}
    )

    def _do_import() -> None:
        page.goto(BASE_URL)
        page.locator('button:has-text("Import JSON")').click()
        page.wait_for_selector('[data-testid="json-import-modal"]', timeout=5000)
        next_btn = page.locator('[data-testid="import-next-btn"]')
        if next_btn.count() > 0:
            next_btn.click()
        page.locator('[data-testid="raw-json-input"]').fill(payload)
        page.locator('[data-testid="import-submit-btn"]').click()
        page.locator("text=Successfully imported").wait_for(timeout=5000)

    _do_import()
    count_after_first = risk_count(page, BASE_URL)

    _do_import()
    count_after_second = risk_count(page, BASE_URL)

    # Same fixed id -> the second import updates in place, not a new row.
    assert count_after_second == count_after_first
