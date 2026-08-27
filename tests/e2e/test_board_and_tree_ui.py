"""E2E browser tests for the WBS tree controls and the kanban board.

Covers two defects found by clicking through every button in the dashboard:

* "Collapse all" was a no-op. It wrote ``false`` only for the node ids already
  present in the expansion dict, which on a freshly-rendered tree is none of
  them, so the button did nothing at all.
* The kanban board was read-only. ``TaskStore.update()`` could always move a
  task between statuses, but nothing reachable from the browser called it, so
  a card could be opened and read but never moved to Done.

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
        pytest.skip("No server on localhost:8000 for board/tree E2E tests")


def _open_tab(page: Page, tab: str) -> None:
    page.goto(BASE_URL)
    page.wait_for_selector(".stat-tile", timeout=10000)
    page.click('[data-testid="nav-detail"]')
    page.click(f'button.tab-btn:has-text("{tab}")')


@pytest.fixture
def wbs_page(page: Page) -> Page:
    _open_tab(page, "WBS")
    page.wait_for_selector(".wbs-tree", timeout=5000)
    return page


@pytest.fixture
def board_page(page: Page) -> Page:
    _open_tab(page, "Kanban")
    page.wait_for_selector(".kanban-board", timeout=5000)
    return page


def _counts(page: Page) -> list[int]:
    """Card count per column, in board order: To Do, Blocked, Done."""
    return [int(t) for t in page.locator(".kanban-count").all_text_contents()]


# --------------------------------------------------------------------------- #
# WBS tree
# --------------------------------------------------------------------------- #


def test_collapse_all_hides_descendants(wbs_page: Page):
    """The defect: this used to leave every row on screen."""
    before = wbs_page.locator(".wbs-item").count()
    assert before > 0, "no tree to collapse — check the fixture data"

    wbs_page.click('button:has-text("Collapse all")')
    wbs_page.wait_for_timeout(300)
    after = wbs_page.locator(".wbs-item").count()
    assert after < before, f"Collapse all did nothing: {before} rows -> {after}"


def test_collapse_all_leaves_exactly_the_roots(wbs_page: Page):
    roots = int(
        wbs_page.locator(".result-count").inner_text().split()[0]
    )
    wbs_page.click('button:has-text("Collapse all")')
    wbs_page.wait_for_timeout(300)
    assert wbs_page.locator(".wbs-item").count() == roots


def test_expand_all_restores_every_row(wbs_page: Page):
    before = wbs_page.locator(".wbs-item").count()
    wbs_page.click('button:has-text("Collapse all")')
    wbs_page.wait_for_timeout(300)
    wbs_page.click('button:has-text("Expand all")')
    wbs_page.wait_for_timeout(300)
    assert wbs_page.locator(".wbs-item").count() == before


def test_single_node_toggle_still_works_after_collapse_all(wbs_page: Page):
    """The per-node override must survive the bulk default being changed."""
    wbs_page.click('button:has-text("Collapse all")')
    wbs_page.wait_for_timeout(300)
    collapsed = wbs_page.locator(".wbs-item").count()

    wbs_page.locator(".wbs-toggle").first.click()
    wbs_page.wait_for_timeout(300)
    assert wbs_page.locator(".wbs-item").count() > collapsed


def test_single_node_toggle_still_works_after_expand_all(wbs_page: Page):
    wbs_page.click('button:has-text("Expand all")')
    wbs_page.wait_for_timeout(300)
    expanded = wbs_page.locator(".wbs-item").count()

    wbs_page.locator(".wbs-toggle").first.click()
    wbs_page.wait_for_timeout(300)
    assert wbs_page.locator(".wbs-item").count() < expanded


# --------------------------------------------------------------------------- #
# Kanban board
# --------------------------------------------------------------------------- #


def test_every_card_has_a_done_control(board_page: Page):
    cards = board_page.locator(".kanban-card")
    assert cards.count() > 0
    assert board_page.locator(".kanban-card .card-check").count() == cards.count()


def test_card_check_moves_a_task_to_done(board_page: Page):
    before = _counts(board_page)
    board_page.locator(".kanban-col").first.locator(".card-check").first.click()
    board_page.wait_for_timeout(2000)
    after = _counts(board_page)

    assert after[0] == before[0] - 1, f"To Do should shrink: {before} -> {after}"
    assert after[2] == before[2] + 1, f"Done should grow: {before} -> {after}"

    # Put it back so the test is repeatable against a live database.
    board_page.locator(".kanban-col").nth(2).locator(
        ".card-check.is-done"
    ).first.click()
    board_page.wait_for_timeout(2000)


def test_done_cards_show_a_filled_check(board_page: Page):
    done_col = board_page.locator(".kanban-col").nth(2)
    if done_col.locator(".kanban-card").count() == 0:
        pytest.skip("no closed tasks in the fixture data")
    assert done_col.locator(".card-check.is-done").count() > 0
    # And a To Do card must not be showing one.
    todo = board_page.locator(".kanban-col").first
    assert todo.locator(".card-check.is-done").count() == 0


def test_card_check_does_not_open_the_detail_modal(board_page: Page):
    """Ticking a card off must not also pop its detail dialog."""
    board_page.locator(".kanban-col").first.locator(".card-check").first.click()
    board_page.wait_for_timeout(1800)
    assert board_page.locator(".modal-status").count() == 0

    board_page.locator(".kanban-col").nth(2).locator(
        ".card-check.is-done"
    ).first.click()
    board_page.wait_for_timeout(1800)


def test_modal_shows_the_current_status_as_active(board_page: Page):
    board_page.locator(".kanban-col").first.locator(
        ".kanban-card-title"
    ).first.click()
    board_page.wait_for_selector(".modal-status", timeout=3000)
    active = board_page.locator(".modal-status .segmented button.active")
    assert active.count() == 1
    assert active.inner_text() == "To Do"


def test_modal_offers_all_three_columns(board_page: Page):
    board_page.locator(".kanban-col").first.locator(
        ".kanban-card-title"
    ).first.click()
    board_page.wait_for_selector(".modal-status", timeout=3000)
    labels = board_page.locator(".modal-status .segmented button").all_text_contents()
    assert labels == ["To Do", "Blocked", "Done"]


def test_modal_status_change_moves_the_card_and_closes(board_page: Page):
    before = _counts(board_page)
    board_page.locator(".kanban-col").first.locator(
        ".kanban-card-title"
    ).first.click()
    board_page.wait_for_selector(".modal-status", timeout=3000)
    board_page.click('.modal-status .segmented button:has-text("Blocked")')
    board_page.wait_for_timeout(2000)

    after = _counts(board_page)
    assert after[1] == before[1] + 1, f"Blocked should grow: {before} -> {after}"
    assert board_page.locator(".modal-status").count() == 0, "modal stayed open"

    # Restore.
    board_page.locator(".kanban-col").nth(1).locator(
        ".kanban-card-title"
    ).first.click()
    board_page.wait_for_selector(".modal-status", timeout=3000)
    board_page.click('.modal-status .segmented button:has-text("To Do")')
    board_page.wait_for_timeout(2000)


def test_status_change_survives_a_reload(board_page: Page):
    """The move must reach the database, not just the rendered board."""
    before = _counts(board_page)
    board_page.locator(".kanban-col").first.locator(".card-check").first.click()
    board_page.wait_for_timeout(2000)

    board_page.goto(BASE_URL)
    board_page.wait_for_selector(".stat-tile", timeout=10000)
    board_page.click('[data-testid="nav-detail"]')
    board_page.click('button.tab-btn:has-text("Kanban")')
    board_page.wait_for_selector(".kanban-board", timeout=5000)

    after = _counts(board_page)
    assert after[2] == before[2] + 1, f"move did not persist: {before} -> {after}"

    board_page.locator(".kanban-col").nth(2).locator(
        ".card-check.is-done"
    ).first.click()
    board_page.wait_for_timeout(2000)


def test_board_raises_no_console_errors(board_page: Page):
    errors: list[str] = []
    board_page.on("pageerror", lambda e: errors.append(str(e)))
    board_page.locator(".kanban-col").first.locator(".card-check").first.click()
    board_page.wait_for_timeout(2000)
    board_page.locator(".kanban-col").nth(2).locator(
        ".card-check.is-done"
    ).first.click()
    board_page.wait_for_timeout(2000)
    assert not errors, errors
