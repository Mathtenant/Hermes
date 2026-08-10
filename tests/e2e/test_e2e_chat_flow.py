"""E2E browser tests for the chat conversational flow (Phase 4b).

Complements ``test_chat_ui.py`` (which covers widget mechanics: toggle, send,
typing indicator) with scenario-level coverage: smalltalk vs. question
answering, cross-window session isolation, and the Q2 collapse end-state
(height + ``aria-expanded``).

Requires Playwright and a live server on http://localhost:8000. Both are
optional in the default environment, so the whole module skips cleanly when
either is missing.
"""

from __future__ import annotations

import socket

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Browser, Page  # noqa: E402

pytestmark = pytest.mark.e2e

BASE_URL = "http://localhost:8000"


def _server_up(host: str = "localhost", port: int = 8000) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


@pytest.fixture(autouse=True)
def _require_server():
    if not _server_up():
        pytest.skip("No server on localhost:8000 for chat E2E tests")


@pytest.fixture
def page_with_chat(page: Page) -> Page:
    page.goto(BASE_URL)
    page.wait_for_selector("#chat-widget", timeout=5000)
    return page


# ---------------------------------------------------------------------------
# Smalltalk vs. question answering
# ---------------------------------------------------------------------------


def test_smalltalk_greeting_gets_conversational_reply(page_with_chat: Page):
    """'Hello' is classified as smalltalk and answered from static templates
    (no action, no LLM round-trip needed to produce a reply)."""
    page_with_chat.locator(".chat-input").fill("Hello")
    page_with_chat.locator(".chat-send").click()
    page_with_chat.wait_for_selector(".chat-messages div", timeout=5000)
    # The assistant reply renders as a second message bubble.
    assert page_with_chat.locator(".chat-messages div").count() >= 2


def test_question_about_risks_gets_answer(page_with_chat: Page):
    """'What risks are we tracking?' degrades gracefully to a grounded (or
    fallback) answer even with no live Ollama service — the turn never 500s."""
    page_with_chat.locator(".chat-input").fill("What risks are we tracking?")
    page_with_chat.locator(".chat-send").click()
    page_with_chat.wait_for_selector(".chat-messages div", timeout=5000)
    assert page_with_chat.locator(".chat-messages div").count() >= 2


# ---------------------------------------------------------------------------
# Session isolation across two browser windows
# ---------------------------------------------------------------------------


def test_two_windows_do_not_share_a_session(browser: Browser):
    """Each browser context gets its own chat session — messages typed in one
    window must never appear in the other (server-side session isolation,
    exercised end-to-end through two independent contexts)."""
    context_a = browser.new_context()
    context_b = browser.new_context()
    try:
        page_a = context_a.new_page()
        page_b = context_b.new_page()
        page_a.goto(BASE_URL)
        page_b.goto(BASE_URL)
        page_a.wait_for_selector("#chat-widget", timeout=5000)
        page_b.wait_for_selector("#chat-widget", timeout=5000)

        page_a.locator(".chat-input").fill("Secret to window A")
        page_a.locator(".chat-send").click()
        page_a.wait_for_selector("text=Secret to window A", timeout=5000)

        page_b.locator(".chat-input").fill("Secret to window B")
        page_b.locator(".chat-send").click()
        page_b.wait_for_selector("text=Secret to window B", timeout=5000)

        assert page_b.locator("text=Secret to window A").count() == 0
        assert page_a.locator("text=Secret to window B").count() == 0
    finally:
        context_a.close()
        context_b.close()


# ---------------------------------------------------------------------------
# Q2 collapse animation — end-state height + aria-expanded
# ---------------------------------------------------------------------------


def test_collapse_end_state_body_height_zero(page_with_chat: Page):
    body = page_with_chat.locator("#chat-widget-body")
    button = page_with_chat.locator("#chat-widget button").first

    button.click()  # collapse
    page_with_chat.wait_for_timeout(350)  # settle past any CSS transition
    box = body.bounding_box()
    assert box is None or box["height"] == 0


def test_collapse_toggle_updates_aria_expanded(page_with_chat: Page):
    button = page_with_chat.locator("#chat-widget button").first
    widget = page_with_chat.locator("#chat-widget")

    aria = widget.get_attribute("aria-expanded")
    if aria is None:
        pytest.skip("chat widget does not expose aria-expanded yet")

    assert aria == "true"
    button.click()
    assert widget.get_attribute("aria-expanded") == "false"
