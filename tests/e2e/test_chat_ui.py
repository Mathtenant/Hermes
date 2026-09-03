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
def page_with_chat(page: Page) -> Page:
    page.goto(BASE_URL)
    page.wait_for_selector("#chat-widget", timeout=5000)
    return page


def test_chat_widget_visible(page_with_chat: Page):
    assert page_with_chat.locator("#chat-widget").is_visible()


def test_chat_widget_toggle_open_close(page_with_chat: Page):
    toggle_btn = page_with_chat.locator(".chat-toggle").first
    toggle_btn.click()
    assert page_with_chat.locator(".chat-input").count() == 0
    toggle_btn.click()
    assert page_with_chat.locator(".chat-input").is_visible()


def test_send_message(page_with_chat: Page):
    page_with_chat.locator(".chat-input").fill("Hello")
    page_with_chat.locator(".chat-send").click()
    assert page_with_chat.locator("text=Hello").first.is_visible()


def test_assistant_response_appears(page_with_chat: Page):
    page_with_chat.locator(".chat-input").fill("Show me the risks")
    page_with_chat.locator(".chat-send").click()
    page_with_chat.wait_for_selector(".chat-messages div", timeout=5000)


def test_send_on_enter(page_with_chat: Page):
    field = page_with_chat.locator(".chat-input")
    field.fill("Test message")
    field.press("Enter")
    assert page_with_chat.locator("text=Test message").first.is_visible()


def test_empty_message_not_sent(page_with_chat: Page):
    before = page_with_chat.locator(".chat-messages div").count()
    page_with_chat.locator(".chat-send").click()
    after = page_with_chat.locator(".chat-messages div").count()
    assert after == before


def test_typing_indicator(page_with_chat: Page):
    page_with_chat.locator(".chat-input").fill("Test")
    page_with_chat.locator(".chat-send").click()
    page_with_chat.wait_for_selector(".chat-typing", timeout=2000)


def test_error_message(page_with_chat: Page):
    """A failed request must surface an error in the transcript.

    The pattern has to cover /api/chat/message/stream, which is what the widget
    actually calls; a bare "**/api/chat/message" never matches it, so the abort
    silently did nothing and the request succeeded.
    """
    page_with_chat.route("**/api/chat/message*", lambda route: route.abort())
    page_with_chat.route("**/api/chat/message/**", lambda route: route.abort())
    page_with_chat.locator(".chat-input").fill("Test")
    page_with_chat.locator(".chat-send").click()
    page_with_chat.wait_for_selector("text=Error", timeout=5000)


def test_multiple_exchanges(page_with_chat: Page):
    field = page_with_chat.locator(".chat-input")
    for i in range(3):
        field.fill(f"Message {i}")
        page_with_chat.locator(".chat-send").click()
        page_with_chat.wait_for_selector(f"text=Message {i}", timeout=5000)


def test_suggestion_buttons(page_with_chat: Page):
    page_with_chat.locator(".chat-input").fill("Show risks")
    page_with_chat.locator(".chat-send").click()
    page_with_chat.wait_for_timeout(500)


def test_message_persistence(page_with_chat: Page):
    field = page_with_chat.locator(".chat-input")
    field.fill("First message")
    page_with_chat.locator(".chat-send").click()
    page_with_chat.wait_for_selector("text=First message", timeout=5000)
    field.fill("Second message")
    page_with_chat.locator(".chat-send").click()
    assert page_with_chat.locator("text=First message").count() > 0
    assert page_with_chat.locator("text=Second message").count() > 0


def test_message_alignment(page_with_chat: Page):
    page_with_chat.locator(".chat-input").fill("Align test")
    page_with_chat.locator(".chat-send").click()
    assert page_with_chat.locator("text=Align test").first.is_visible()


def test_input_field_clears_after_send(page_with_chat: Page):
    """Wait for the message inside the CHAT, not for the word anywhere.

    A bare "text=Test" matched six elements once the dashboard started
    landing on Aufgaben & Termine, whose rows include titles like "Testdaten
    liefern" — so the wait resolved against a to-do that was on screen before
    the message was ever sent. Scoping to the chat log also makes the test
    say what it means.
    """
    field = page_with_chat.locator(".chat-input")
    field.fill("Test")
    assert field.input_value() == "Test"
    page_with_chat.locator(".chat-send").click()
    page_with_chat.locator(".chat-messages", has_text="Test").first.wait_for(
        timeout=5000
    )
    assert page_with_chat.locator(".chat-input").input_value() == ""


def test_widget_header_title(page_with_chat: Page):
    assert page_with_chat.locator("text=Hermes Chat").is_visible()


def test_send_button_present(page_with_chat: Page):
    assert page_with_chat.locator(".chat-send").is_visible()


# --------------------------------------------------------------------------- #
# Q2 — chat panel collapse defect
# --------------------------------------------------------------------------- #


def test_chat_widget_collapse(page_with_chat: Page):
    """Chat widget collapses when the '−' button is clicked, and re-expands."""
    widget = page_with_chat.locator("#chat-widget")
    button = widget.locator("button").first
    body = page_with_chat.locator("#chat-widget-body")

    # Initial state: expanded.
    assert button.text_content() == "−"
    assert body.is_visible()

    # Click to collapse.
    button.click()
    assert page_with_chat.locator("#chat-widget button").first.text_content() == "+"
    assert page_with_chat.locator("#chat-widget-body").is_hidden()

    # Click to expand.
    page_with_chat.locator("#chat-widget button").first.click()
    assert page_with_chat.locator("#chat-widget button").first.text_content() == "−"
    assert page_with_chat.locator("#chat-widget-body").is_visible()


def test_chat_widget_collapse_persists(page_with_chat: Page):
    """Collapsed state persists across a page reload (sessionStorage)."""
    button = page_with_chat.locator("#chat-widget button").first

    # Collapse.
    button.click()
    assert page_with_chat.locator("#chat-widget button").first.text_content() == "+"

    # Reload — the restored state should still be collapsed.
    page_with_chat.reload()
    page_with_chat.wait_for_selector("#chat-widget", timeout=5000)
    assert page_with_chat.locator("#chat-widget button").first.text_content() == "+"


# --------------------------------------------------------------------------- #
# Tab title flash — notify when inference finishes while the tab is in the
# background.
#
# Headless Chromium reports every page as visible, so a genuinely backgrounded
# tab cannot be produced here. `document.hidden` is overridden instead, which
# is the exact input the widget branches on; the browser's own setting of that
# flag when you switch tabs is standard behaviour, not our code.
# --------------------------------------------------------------------------- #

_VISIBILITY_SHIM = """
    window.__hidden = false;
    Object.defineProperty(document, 'hidden', {
        configurable: true,
        get: function () { return window.__hidden; },
    });
    window.__setHidden = function (v) {
        window.__hidden = v;
        document.dispatchEvent(new Event('visibilitychange'));
    };
"""


@pytest.fixture
def page_hidden_control(page: Page) -> Page:
    """Chat page whose document.hidden the test can drive."""
    page.add_init_script(_VISIBILITY_SHIM)
    page.goto(BASE_URL)
    page.wait_for_selector(".chat-input", timeout=5000)
    return page


def _send(page: Page, text: str) -> None:
    page.locator(".chat-input").fill(text)
    page.locator(".chat-send").click()
    page.wait_for_timeout(2000)


def _titles_over(page: Page, samples: int = 12, gap_ms: int = 400) -> set[str]:
    """Sample document.title repeatedly to observe the flash alternating."""
    seen: set[str] = set()
    for _ in range(samples):
        seen.add(page.title())
        page.wait_for_timeout(gap_ms)
    return seen


def test_title_untouched_while_tab_visible(page_hidden_control: Page):
    """No notice when the user is looking — the streamed bubble is the signal."""
    original = page_hidden_control.title()
    _send(page_hidden_control, "hello there")
    assert page_hidden_control.title() == original


def test_title_flashes_when_reply_lands_on_hidden_tab(page_hidden_control: Page):
    original = page_hidden_control.title()
    page_hidden_control.evaluate("window.__setHidden(true)")
    _send(page_hidden_control, "what risks are we tracking?")

    seen = _titles_over(page_hidden_control)
    assert any("Hermes reply ready" in t for t in seen), seen
    # Must alternate — a static title is easy to miss in a tab strip.
    assert original in seen, seen


def test_title_flash_counts_multiple_replies(page_hidden_control: Page):
    page_hidden_control.evaluate("window.__setHidden(true)")
    _send(page_hidden_control, "what risks are we tracking?")
    _send(page_hidden_control, "show me the plan")

    seen = _titles_over(page_hidden_control, samples=8, gap_ms=300)
    assert any("(2)" in t and "replies" in t for t in seen), seen


def test_title_restored_when_tab_becomes_visible(page_hidden_control: Page):
    original = page_hidden_control.title()
    page_hidden_control.evaluate("window.__setHidden(true)")
    _send(page_hidden_control, "what risks are we tracking?")
    # Sample rather than checking one instant: the title alternates, so a
    # single read can legitimately land on the base-title phase.
    assert any("Hermes reply ready" in t for t in _titles_over(page_hidden_control, 4, 400))

    page_hidden_control.evaluate("window.__setHidden(false)")
    page_hidden_control.wait_for_timeout(300)
    assert page_hidden_control.title() == original
    # And the interval must actually be cleared, not just skipped once.
    page_hidden_control.wait_for_timeout(2000)
    assert page_hidden_control.title() == original


def test_title_flash_cycle_resets_after_return(page_hidden_control: Page):
    """A later reply starts a fresh count instead of resuming a stale one."""
    page_hidden_control.evaluate("window.__setHidden(true)")
    _send(page_hidden_control, "what risks are we tracking?")
    _send(page_hidden_control, "show me the plan")
    page_hidden_control.evaluate("window.__setHidden(false)")
    page_hidden_control.wait_for_timeout(300)

    page_hidden_control.evaluate("window.__setHidden(true)")
    _send(page_hidden_control, "hello again")
    seen = _titles_over(page_hidden_control, samples=6, gap_ms=300)
    assert any("Hermes reply ready" in t for t in seen), seen
    assert not any("(2)" in t for t in seen), seen


def test_rapid_sends_do_not_lose_messages(page_with_chat: Page):
    """Sending several messages quickly must not drop any of them.

    render() used to replace the widget's whole subtree on every streamed
    token. If that landed while text was being written into the composer, the
    value ended up on a node already detached from the document, so the send
    read an empty field and the message vanished with no error. Preserving the
    value across the swap could not fix it — the race is with the write itself
    — so the composer is now built once and only the message list is
    refreshed.
    """
    for i in range(3):
        page_with_chat.locator(".chat-input").fill(f"Rapid {i}")
        page_with_chat.locator(".chat-send").click()

    page_with_chat.wait_for_timeout(3500)
    sent = page_with_chat.evaluate(
        "window.ChatWidget.state.messages"
        ".filter(m => m.role === 'user').map(m => m.content)"
    )
    for i in range(3):
        assert f"Rapid {i}" in sent, f"lost 'Rapid {i}' — got {sent}"


def test_composer_keeps_text_while_a_reply_streams(page_with_chat: Page):
    """Typing the next question while a reply arrives must not be wiped."""
    page_with_chat.locator(".chat-input").fill("First question")
    page_with_chat.locator(".chat-send").click()
    # Type immediately, while the answer is still streaming in.
    page_with_chat.locator(".chat-input").fill("Second question, still typing")
    page_with_chat.wait_for_timeout(2500)
    assert (
        page_with_chat.locator(".chat-input").input_value()
        == "Second question, still typing"
    )
