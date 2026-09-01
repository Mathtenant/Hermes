"""E2E browser tests for the sidebar order, the rename, and the create dialog.

Requires Playwright and a live server on http://localhost:8000; the module
skips cleanly when either is missing.
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
        pytest.skip("No server on localhost:8000")


@pytest.fixture
def app_page(page: Page) -> Page:
    """A page at the shipped sidebar order.

    The reset is a one-off `evaluate` rather than an init script: an init
    script re-runs on every navigation, so it would wipe the stored order
    again on the reloads the persistence tests depend on — and those tests
    would then pass for the wrong reason, or fail for one.
    """
    page.add_init_script(
        "try{sessionStorage.setItem("
        "'panel-collapsed-chat-widget-body','true')}catch(e){}"
    )
    page.goto(BASE_URL)
    page.wait_for_selector(".stat-tile", timeout=10000)
    page.evaluate("try{localStorage.removeItem('hermes-nav-order')}catch(e){}")
    page.reload()
    page.wait_for_selector(".stat-tile", timeout=10000)
    return page


def _nav(page: Page) -> list[str]:
    return [t.strip() for t in page.locator(".nav-btn span:nth-child(2)").all_text_contents()]


# --------------------------------------------------------------------------- #
# Rename
# --------------------------------------------------------------------------- #


def test_the_sidebar_says_todo(app_page: Page):
    assert "Todo" in _nav(app_page)
    assert "Pendenzen" not in _nav(app_page)


def test_the_screen_and_its_tab_say_todo(app_page: Page):
    app_page.click('[data-testid="nav-pendenzen"]')
    app_page.wait_for_timeout(500)
    assert "Todo" in app_page.locator(".page-title").inner_text()
    tabs = app_page.locator(".tab-bar .tab-btn").all_text_contents()
    assert any("Todos" in t for t in tabs)


def test_the_overview_hero_says_todo(app_page: Page):
    assert "Todo" in app_page.locator(".hero-label").inner_text()


def test_the_route_key_is_unchanged_by_the_rename(app_page: Page):
    """Only labels moved. The hash, the API and the stored data keep the
    original name, so existing links and imports still work."""
    app_page.click('[data-testid="nav-pendenzen"]')
    app_page.wait_for_timeout(400)
    assert app_page.url.endswith("#/pendenzen")


# --------------------------------------------------------------------------- #
# Reordering
# --------------------------------------------------------------------------- #


def test_alt_arrow_moves_the_focused_item(app_page: Page):
    """Drag is not the only way in — the order must be reachable by keyboard."""
    before = _nav(app_page)
    app_page.locator('[data-testid="nav-risks"]').focus()
    app_page.keyboard.press("Alt+ArrowUp")
    app_page.wait_for_timeout(300)
    after = _nav(app_page)
    assert after != before
    assert after.index("Risks") == before.index("Risks") - 1


def test_alt_arrow_down_moves_the_other_way(app_page: Page):
    before = _nav(app_page)
    app_page.locator('[data-testid="nav-projects"]').focus()
    app_page.keyboard.press("Alt+ArrowDown")
    app_page.wait_for_timeout(300)
    assert _nav(app_page).index("Projects") == before.index("Projects") + 1


def test_the_ends_of_the_list_are_not_wrapped_past(app_page: Page):
    before = _nav(app_page)
    app_page.locator('[data-testid="nav-overview"]').focus()
    app_page.keyboard.press("Alt+ArrowUp")
    app_page.wait_for_timeout(300)
    assert _nav(app_page) == before


def test_dragging_reorders(app_page: Page):
    before = _nav(app_page)
    app_page.locator('[data-testid="nav-reviews"]').drag_to(
        app_page.locator('[data-testid="nav-projects"]')
    )
    app_page.wait_for_timeout(400)
    after = _nav(app_page)
    assert after != before
    assert after.index("Reviews") < after.index("Projects")


def test_the_order_survives_a_reload(app_page: Page):
    app_page.locator('[data-testid="nav-risks"]').focus()
    app_page.keyboard.press("Alt+ArrowUp")
    app_page.wait_for_timeout(300)
    moved = _nav(app_page)

    # Not the fixture's goto: that clears the stored order on init.
    app_page.reload()
    app_page.wait_for_selector(".stat-tile", timeout=10000)
    assert _nav(app_page) == moved


def test_reordering_does_not_break_navigation(app_page: Page):
    """A draggable button still has to behave like a button."""
    app_page.locator('[data-testid="nav-risks"]').focus()
    app_page.keyboard.press("Alt+ArrowUp")
    app_page.wait_for_timeout(300)
    app_page.click('[data-testid="nav-risks"]')
    app_page.wait_for_timeout(500)
    assert app_page.locator(".page-title").inner_text().strip() == "Risks"


def test_the_shortcut_digits_do_not_move_with_the_rows(app_page: Page):
    """A key that followed the row would be unlearnable, so the digits stay
    bound to screens rather than positions."""
    app_page.locator('[data-testid="nav-risks"]').focus()
    app_page.keyboard.press("Alt+ArrowUp")
    app_page.wait_for_timeout(300)
    app_page.locator("body").click()
    app_page.keyboard.press("6")          # 6 is Risks in the canonical list
    app_page.wait_for_timeout(500)
    assert app_page.locator(".page-title").inner_text().strip() == "Risks"


def test_an_unknown_stored_key_is_ignored(app_page: Page):
    """A screen removed in a later version must not leave a hole, and one
    added must not vanish."""
    app_page.evaluate(
        "localStorage.setItem('hermes-nav-order',"
        " JSON.stringify(['risks','gibt-es-nicht','overview']))"
    )
    app_page.reload()
    app_page.wait_for_selector(".stat-tile", timeout=10000)
    nav = _nav(app_page)
    assert nav[0] == "Risks"          # stored order honoured
    assert nav[1] == "Overview"
    assert "Todo" in nav              # screens absent from the stored list survive
    assert len(nav) == 7


def test_corrupt_stored_order_falls_back_to_the_default(app_page: Page):
    app_page.evaluate("localStorage.setItem('hermes-nav-order','not json')")
    app_page.reload()
    app_page.wait_for_selector(".stat-tile", timeout=10000)
    assert _nav(app_page)[0] == "Overview"
    assert len(_nav(app_page)) == 7


# --------------------------------------------------------------------------- #
# Create dialog
# --------------------------------------------------------------------------- #


def _open_create(page: Page) -> None:
    page.click('[data-testid="open-create"]')
    page.wait_for_selector('[data-testid="create-submit"]', timeout=3000)


def test_the_create_button_opens_a_dialog(app_page: Page):
    _open_create(app_page)
    kinds = app_page.locator(".prompt-kind").all_text_contents()
    assert [k.strip() for k in kinds] == ["Todo", "Arbeitspaket", "Projekt"]


def test_a_todo_can_be_created_and_shows_up(app_page: Page):
    before = int(app_page.locator('[data-testid="nav-pendenzen"] .nav-count').inner_text())
    _open_create(app_page)
    app_page.fill('[data-testid="create-title"]', "E2E Neuer Punkt")
    app_page.fill('[data-testid="create-owner"]', "E2E Owner")
    app_page.select_option('[data-testid="create-priority"]', "high")
    app_page.click('[data-testid="create-submit"]')
    app_page.wait_for_timeout(2500)

    after = int(app_page.locator('[data-testid="nav-pendenzen"] .nav-count').inner_text())
    assert after == before + 1

    app_page.click('[data-testid="nav-pendenzen"]')
    app_page.fill('[data-testid="pendenzen-search"]', "E2E Neuer Punkt")
    app_page.wait_for_timeout(500)
    row = app_page.locator('tbody tr:has-text("E2E Neuer Punkt")').first.inner_text()
    assert "E2E Owner" in row
    assert "high" in row


def test_submit_is_disabled_until_there_is_a_title(app_page: Page):
    _open_create(app_page)
    assert app_page.locator('[data-testid="create-submit"]').is_disabled()
    app_page.fill('[data-testid="create-title"]', "X")
    assert app_page.locator('[data-testid="create-submit"]').is_enabled()


def test_switching_kind_swaps_the_fields(app_page: Page):
    _open_create(app_page)
    assert app_page.locator('[data-testid="create-priority"]').count() == 1
    app_page.click('[data-testid="create-kind-task"]')
    assert app_page.locator('[data-testid="create-node-kind"]').count() == 1
    assert app_page.locator('[data-testid="create-priority"]').count() == 0
    app_page.click('[data-testid="create-kind-project"]')
    assert app_page.locator('[data-testid="create-project-id"]').count() == 1
    assert app_page.locator('[data-testid="create-title"]').count() == 0


def test_a_server_rejection_is_shown_rather_than_swallowed(app_page: Page):
    _open_create(app_page)
    app_page.click('[data-testid="create-kind-project"]')
    app_page.fill('[data-testid="create-project-id"]', "../escaped")
    app_page.click('[data-testid="create-submit"]')
    app_page.wait_for_selector(".notice-error", timeout=4000)
    # The dialog stays open so the value can be corrected.
    assert app_page.locator('[data-testid="create-submit"]').count() == 1


def test_escape_closes_the_dialog(app_page: Page):
    _open_create(app_page)
    app_page.keyboard.press("Escape")
    app_page.wait_for_timeout(400)
    assert app_page.locator('[data-testid="create-submit"]').count() == 0


def test_creating_raises_no_console_errors(app_page: Page):
    errors: list[str] = []
    app_page.on("pageerror", lambda e: errors.append(str(e)))
    _open_create(app_page)
    app_page.click('[data-testid="create-kind-task"]')
    app_page.fill('[data-testid="create-title"]', "E2E Arbeitspaket")
    app_page.click('[data-testid="create-submit"]')
    app_page.wait_for_timeout(2500)
    assert not errors, errors
