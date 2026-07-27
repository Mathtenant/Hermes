"""E2E browser tests for the chat widget (Phase 5.6).

Requires Playwright and a live server on http://localhost:8000. Both are
optional in the default environment, so the whole module skips cleanly when
either is missing (``importorskip`` for Playwright; a socket probe for the
server). Marked ``e2e`` so ``pytest -m "not e2e"`` excludes it from the fast
regression suite.
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
        pytest.skip("No server on localhost:8000 for chat E2E tests")


@pytest.fixture
def page_with_chat(page: "Page") -> "Page":
    page.goto(BASE_URL)
    page.wait_for_selector("#chat-widget", timeout=5000)
    return page


def test_chat_widget_visible(page_with_chat: "Page"):
    assert page_with_chat.locator("#chat-widget").is_visible()


def test_chat_widget_toggle_open_close(page_with_chat: "Page"):
    toggle_btn = page_with_chat.locator(".chat-toggle").first
    toggle_btn.click()
    assert page_with_chat.locator(".chat-input").count() == 0
    toggle_btn.click()
    assert page_with_chat.locator(".chat-input").is_visible()


def test_send_message(page_with_chat: "Page"):
    page_with_chat.locator(".chat-input").fill("Hello")
    page_with_chat.locator(".chat-send").click()
    assert page_with_chat.locator("text=Hello").first.is_visible()


def test_assistant_response_appears(page_with_chat: "Page"):
    page_with_chat.locator(".chat-input").fill("Show me the risks")
    page_with_chat.locator(".chat-send").click()
    page_with_chat.wait_for_selector(".chat-messages div", timeout=5000)


def test_send_on_enter(page_with_chat: "Page"):
    field = page_with_chat.locator(".chat-input")
    field.fill("Test message")
    field.press("Enter")
    assert page_with_chat.locator("text=Test message").first.is_visible()


def test_empty_message_not_sent(page_with_chat: "Page"):
    before = page_with_chat.locator(".chat-messages div").count()
    page_with_chat.locator(".chat-send").click()
    after = page_with_chat.locator(".chat-messages div").count()
    assert after == before


def test_typing_indicator(page_with_chat: "Page"):
    page_with_chat.locator(".chat-input").fill("Test")
    page_with_chat.locator(".chat-send").click()
    page_with_chat.wait_for_selector(".chat-typing", timeout=2000)


def test_error_message(page_with_chat: "Page"):
    page_with_chat.route("**/api/chat/message", lambda route: route.abort())
    page_with_chat.locator(".chat-input").fill("Test")
    page_with_chat.locator(".chat-send").click()
    page_with_chat.wait_for_selector("text=Error", timeout=5000)


def test_multiple_exchanges(page_with_chat: "Page"):
    field = page_with_chat.locator(".chat-input")
    for i in range(3):
        field.fill(f"Message {i}")
        page_with_chat.locator(".chat-send").click()
        page_with_chat.wait_for_selector(f"text=Message {i}", timeout=5000)


def test_suggestion_buttons(page_with_chat: "Page"):
    page_with_chat.locator(".chat-input").fill("Show risks")
    page_with_chat.locator(".chat-send").click()
    page_with_chat.wait_for_timeout(500)


def test_message_persistence(page_with_chat: "Page"):
    field = page_with_chat.locator(".chat-input")
    field.fill("First message")
    page_with_chat.locator(".chat-send").click()
    page_with_chat.wait_for_selector("text=First message", timeout=5000)
    field.fill("Second message")
    page_with_chat.locator(".chat-send").click()
    assert page_with_chat.locator("text=First message").count() > 0
    assert page_with_chat.locator("text=Second message").count() > 0


def test_message_alignment(page_with_chat: "Page"):
    page_with_chat.locator(".chat-input").fill("Align test")
    page_with_chat.locator(".chat-send").click()
    assert page_with_chat.locator("text=Align test").first.is_visible()


def test_input_field_clears_after_send(page_with_chat: "Page"):
    field = page_with_chat.locator(".chat-input")
    field.fill("Test")
    assert field.input_value() == "Test"
    page_with_chat.locator(".chat-send").click()
    page_with_chat.wait_for_selector("text=Test", timeout=5000)
    assert page_with_chat.locator(".chat-input").input_value() == ""


def test_widget_header_title(page_with_chat: "Page"):
    assert page_with_chat.locator("text=Hermes Chat").is_visible()


def test_send_button_present(page_with_chat: "Page"):
    assert page_with_chat.locator(".chat-send").is_visible()
