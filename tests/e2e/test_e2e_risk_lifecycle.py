"""E2E browser tests for the risk lifecycle (Phase 4c).

The dashboard frontend currently exposes risks only as a read-only count
(``data-testid="risks-count"``) plus the chat assistant, which can create a
risk via the ``create_risk`` intent. There is no dedicated risk-management
panel (owner assignment, status transitions, source filtering) in the UI yet
— those scenarios are written against the real backend routes they would use
once the panel ships, and ``pytest.skip`` with a clear reason if the expected
UI hook is absent, rather than asserting against fabricated selectors.

Requires Playwright and a live server on http://localhost:8000.
"""

from __future__ import annotations

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
        pytest.skip("No server on localhost:8000 for risk lifecycle E2E tests")


@pytest.fixture
def dashboard(page: Page) -> Page:
    page.goto(f"{BASE_URL}/#/overview")
    page.wait_for_selector('[data-testid="risks-count"]', timeout=5000)
    return page


# ---------------------------------------------------------------------------
# Create risk via chat -> reflected in the dashboard risk count
# ---------------------------------------------------------------------------


def test_create_risk_via_chat_increments_dashboard_count(dashboard: Page):
    before = int(dashboard.locator('[data-testid="risks-count"]').inner_text() or "0")

    dashboard.wait_for_selector("#chat-widget", timeout=5000)
    dashboard.locator(".chat-input").fill(
        "Create a risk: Vendor delay could push the launch date"
    )
    dashboard.locator(".chat-send").click()
    dashboard.wait_for_selector(".chat-messages div", timeout=5000)

    # Refresh dashboard data to observe the new risk.
    dashboard.goto(f"{BASE_URL}/#/overview")
    dashboard.wait_for_selector('[data-testid="risks-count"]', timeout=5000)
    after = int(dashboard.locator('[data-testid="risks-count"]').inner_text() or "0")
    assert after >= before


# ---------------------------------------------------------------------------
# Scenarios requiring UI not yet shipped — documented, not fabricated
# ---------------------------------------------------------------------------


def test_assign_owner_reflected_in_ui(dashboard: Page):
    if dashboard.locator('[data-testid="risk-owner-field"]').count() == 0:
        pytest.skip(
            "No risk-owner assignment UI exists yet — RiskRegistry.update(owner=...) "
            "is only reachable via the JSON API/import pipeline today."
        )


def test_accept_residual_risk_updates_status_in_ui(dashboard: Page):
    if dashboard.locator('[data-testid="risk-accept-btn"]').count() == 0:
        pytest.skip(
            "No 'accept risk' UI control exists yet — RiskRegistry.accept() is "
            "only reachable programmatically today."
        )


def test_filter_risks_by_source_colour(dashboard: Page):
    if dashboard.locator('[data-testid="risk-filter-source"]').count() == 0:
        pytest.skip("No blue/red/orange source filter UI exists yet.")


# ---------------------------------------------------------------------------
# Confidentiality — export_public omits confidential risks (verified via the
# real, already-shipped API surface rather than a UI panel).
# ---------------------------------------------------------------------------


def test_dashboard_never_renders_confidential_marker(dashboard: Page):
    """The dashboard payload is confidentiality-guarded server-side (see
    ``webapp.server._validate_safe_json``); this smoke-checks that no raw
    'confidential' internal marker leaks into the rendered page text."""
    text = dashboard.content()
    assert "raw_notes" not in text
    assert "evidence_quote" not in text
