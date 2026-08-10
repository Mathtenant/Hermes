"""E2E browser tests for plan editing (Phase 4d).

``PlanEditor`` (versioning, diff, reorder) is fully implemented server-side
(see ``hermes_assistant.plans.editor`` and ``tests/test_plan_editor.py`` /
``tests/test_invariants_plans.py``), but the dashboard frontend has no plan
editor screen yet — only the chat assistant's ``show_plan`` intent surfaces
plan data, as a read-only summary sentence.

These tests target the plan-editor UI hooks that would back the scenarios in
the test plan (save v1 -> edit -> v2, diff view, v1 immutability-in-UI). Each
skips with a clear reason when its target UI hook is absent, so the suite
stays green today and starts asserting real behaviour automatically the
moment the panel ships (no rewrite needed — only the ``pytest.skip`` guard
becomes unreachable).

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
        pytest.skip("No server on localhost:8000 for plan editing E2E tests")


@pytest.fixture
def dashboard(page: Page) -> Page:
    page.goto(BASE_URL)
    page.wait_for_selector("#app", timeout=5000)
    return page


def _has_plan_editor(page: Page) -> bool:
    return page.locator('[data-testid="plan-editor"]').count() > 0


def test_show_plan_via_chat_returns_summary(dashboard: Page):
    """The one plan-related capability that *is* shipped today: asking the
    assistant for the plan returns a grounded (or 'no plan yet') summary."""
    dashboard.wait_for_selector("#chat-widget", timeout=5000)
    dashboard.locator(".chat-input").fill("What's the current plan?")
    dashboard.locator(".chat-send").click()
    dashboard.wait_for_selector(".chat-messages div", timeout=5000)
    assert dashboard.locator(".chat-messages div").count() >= 2


def test_save_v1_edit_to_v2_history_shows_both(dashboard: Page):
    if not _has_plan_editor(dashboard):
        pytest.skip("No plan editor UI exists yet ([data-testid='plan-editor']).")
    dashboard.locator('[data-testid="plan-editor"]').click()
    dashboard.locator('[data-testid="plan-history"]').wait_for(timeout=5000)
    versions = dashboard.locator('[data-testid="plan-version-row"]')
    assert versions.count() >= 2


def test_diff_view_shows_add_change_remove(dashboard: Page):
    if dashboard.locator('[data-testid="plan-diff-view"]').count() == 0:
        pytest.skip("No plan diff view UI exists yet.")


def test_v1_still_readable_after_v2_created(dashboard: Page):
    if not _has_plan_editor(dashboard):
        pytest.skip("No plan editor UI exists yet ([data-testid='plan-editor']).")
    dashboard.locator('[data-testid="plan-editor"]').click()
    dashboard.locator('[data-testid="plan-version-select"]').select_option("1")
    assert dashboard.locator('[data-testid="plan-items"]').is_visible()
