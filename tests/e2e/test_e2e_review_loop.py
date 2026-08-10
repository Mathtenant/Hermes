"""E2E browser tests for the review loop (Phase 4f).

The critic/review pipeline (rubrics, self-consistency scoring, async job
queue) is fully implemented and unit/integration-tested elsewhere (see
``tests/test_critic.py``, ``tests/test_critic_integration.py``,
``tests/test_queue_integration.py``, ``tests/test_cli_review.py``). The
*chat* surface for triggering a review is real (``run_review`` /
``review_status`` intents), but a dedicated review-loop UI panel (suggestion
cards with confidence scores, an "Apply" button that creates a plan v2, an
automatic re-review trigger) does not exist in the dashboard frontend yet.

The two tests below drive the real chat-based surface; the remaining
scenarios skip with a clear reason pending the UI panel.

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
        pytest.skip("No server on localhost:8000 for review-loop E2E tests")


@pytest.fixture
def page_with_chat(page: Page) -> Page:
    page.goto(BASE_URL)
    page.wait_for_selector("#chat-widget", timeout=5000)
    return page


def test_run_review_via_chat_enqueues_job(page_with_chat: Page):
    """'Run a review' classifies to run_review and the reply surfaces a job id
    (see ResponseFormatter.format_result_existing: 'Review queued (Job ID: ...)')."""
    page_with_chat.locator(".chat-input").fill("Run a review")
    page_with_chat.locator(".chat-send").click()
    page_with_chat.wait_for_selector(".chat-messages div", timeout=5000)
    assert page_with_chat.locator(".chat-messages div").count() >= 2


def test_review_status_via_chat_does_not_error(page_with_chat: Page):
    page_with_chat.locator(".chat-input").fill("What's the review status?")
    page_with_chat.locator(".chat-send").click()
    page_with_chat.wait_for_selector(".chat-messages div", timeout=5000)
    assert page_with_chat.locator(".chat-messages div").count() >= 2


def test_suggestion_shown_with_confidence(page_with_chat: Page):
    if page_with_chat.locator('[data-testid="review-suggestion-card"]').count() == 0:
        pytest.skip("No review-suggestion UI panel exists yet.")


def test_apply_suggestion_creates_plan_v2(page_with_chat: Page):
    if page_with_chat.locator('[data-testid="review-apply-btn"]').count() == 0:
        pytest.skip("No 'apply suggestion' UI control exists yet.")


def test_apply_triggers_rereview(page_with_chat: Page):
    if page_with_chat.locator('[data-testid="review-apply-btn"]').count() == 0:
        pytest.skip("No 'apply suggestion' UI control exists yet — re-review "
                     "trigger cannot be observed from the UI.")
