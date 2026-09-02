"""E2E browser tests for the merged "Aufgaben & Termine" screen.

Todo and Termine & Fristen were never two kinds of thing. They were one
question — what does somebody owe, and by when — split by whether an item
happened to carry a date. In this project's data that split is 9 dated to-dos
against 137 undated ones, with zero title overlap between the tabs, so the
division was strictly arbitrary from the reader's side and answering "what is
next" meant merging two lists by hand.

The merge is one dataset under three lenses. What these tests protect is less
the layout than the two things that make a merge safe: nothing is lost (the
undated items and the decisions both still have a home, and the timeline
admits what it cannot show), and nobody's existing links or sidebar order
break on the way.

Requires Playwright and a live server on http://localhost:8000; the module
skips cleanly when either is missing.
"""

from __future__ import annotations

import socket

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Page, expect  # noqa: E402

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
    """A page at the shipped sidebar order, chat collapsed."""
    page.add_init_script(
        "try{sessionStorage.setItem("
        "'panel-collapsed-chat-widget-body','true')}catch(e){}"
    )
    page.goto(BASE_URL)
    page.wait_for_selector(".stat-tile", timeout=15000)
    page.evaluate("try{localStorage.removeItem('hermes-nav-order')}catch(e){}")
    page.reload()
    page.wait_for_selector(".stat-tile", timeout=15000)
    return page


def _nav(page: Page) -> list[str]:
    return [
        t.strip().split("\n")[0]
        for t in page.locator(".nav-btn span:nth-child(2)").all_text_contents()
    ]


def _open_work(page: Page) -> None:
    page.get_by_role("button", name="Aufgaben & Termine").first.click()
    page.wait_for_selector('[data-testid="work-search"]', timeout=10000)


# --------------------------------------------------------------------------- #
# The sidebar
# --------------------------------------------------------------------------- #


def test_the_two_old_tabs_are_gone(app_page: Page) -> None:
    nav = _nav(app_page)
    assert "Pendenzen" not in nav
    assert "Todo" not in nav
    assert "Termine & Fristen" not in nav


def test_one_merged_tab_replaces_them(app_page: Page) -> None:
    assert "Aufgaben & Termine" in _nav(app_page)


def test_the_merged_tab_counts_both_sources(app_page: Page) -> None:
    """The badge must not silently report only half of what the tab holds."""
    counts = app_page.evaluate(
        """async () => {
            const r = await fetch('/api/dashboard');
            const d = await r.json();
            return d.pendenzen.length + d.ablaufplan.length;
        }"""
    )
    badge = app_page.locator(
        '.nav-btn:has-text("Aufgaben & Termine") .nav-count'
    ).first
    assert badge.inner_text().strip() == str(counts)


# --------------------------------------------------------------------------- #
# Nothing gets stranded
# --------------------------------------------------------------------------- #


def test_an_old_pendenzen_bookmark_still_lands_somewhere(page: Page) -> None:
    """A retired key must forward, not fall through to the default screen."""
    page.goto(f"{BASE_URL}/#/pendenzen")
    page.wait_for_selector('[data-testid="work-search"]', timeout=15000)
    expect(page.locator('[data-testid="lens-liste"]')).to_be_visible()


def test_an_old_plan_bookmark_still_lands_somewhere(page: Page) -> None:
    page.goto(f"{BASE_URL}/#/plan")
    page.wait_for_selector('[data-testid="work-search"]', timeout=15000)
    expect(page.locator('[data-testid="lens-liste"]')).to_be_visible()


def test_a_stored_order_with_retired_keys_keeps_its_slot(page: Page) -> None:
    """The merged tab inherits its predecessor's position.

    Treating it as brand new would append it to the bottom of a sidebar
    somebody deliberately arranged.
    """
    page.goto(BASE_URL)
    page.wait_for_selector(".stat-tile", timeout=15000)
    page.evaluate(
        """() => localStorage.setItem('hermes-nav-order', JSON.stringify(
            ['pendenzen', 'overview', 'projects', 'detail', 'plan',
             'risks', 'reviews']))"""
    )
    page.reload()
    page.wait_for_selector(".stat-tile", timeout=15000)

    assert _nav(page)[0] == "Aufgaben & Termine"


def test_a_stored_order_naming_both_retired_keys_yields_one_tab(page: Page) -> None:
    """Two old keys map to one new one, so the result must not duplicate it."""
    page.goto(BASE_URL)
    page.wait_for_selector(".stat-tile", timeout=15000)
    page.evaluate(
        """() => localStorage.setItem('hermes-nav-order', JSON.stringify(
            ['plan', 'pendenzen', 'overview', 'projects', 'detail',
             'risks', 'reviews']))"""
    )
    page.reload()
    page.wait_for_selector(".stat-tile", timeout=15000)

    nav = _nav(page)
    assert nav.count("Aufgaben & Termine") == 1


# --------------------------------------------------------------------------- #
# The lenses
# --------------------------------------------------------------------------- #


def test_the_list_lens_shows_both_kinds_together(app_page: Page) -> None:
    """The whole point of the merge: one list, both former tabs in it."""
    _open_work(app_page)
    kinds = set(app_page.locator(".kind-chip").all_inner_texts())
    assert {"To-do", "Termin"} <= {k.strip() for k in kinds}


def test_undated_items_have_a_home(app_page: Page) -> None:
    """137 of 146 to-dos carry no date; a timeline alone would strand them."""
    _open_work(app_page)
    heads = " ".join(app_page.locator(".bucket-head").all_inner_texts())
    assert "OHNE TERMIN" in heads.upper()


def test_overdue_work_is_the_first_thing_on_screen(app_page: Page) -> None:
    _open_work(app_page)
    first = app_page.locator(".bucket-head").first.inner_text()
    assert "ÜBERFÄLLIG" in first.upper()


def test_the_timeline_lens_admits_what_it_cannot_show(app_page: Page) -> None:
    """A lens that silently drops 137 rows would be worse than two tabs."""
    _open_work(app_page)
    app_page.locator('[data-testid="lens-zeitstrahl"]').click()
    expect(app_page.locator('[data-testid="undated-notice"]')).to_be_visible(
        timeout=10000
    )


def test_the_timeline_notice_links_back_to_the_list(app_page: Page) -> None:
    _open_work(app_page)
    app_page.locator('[data-testid="lens-zeitstrahl"]').click()
    app_page.locator('[data-testid="undated-notice"] .link-btn').click()
    expect(app_page.locator('[data-testid="work-search"]')).to_be_visible()


def test_the_decisions_view_survived_the_merge(app_page: Page) -> None:
    """Beschlüsse lived inside the old Todo screen and had no tab of its own.

    Dropping that screen without rehoming this would have quietly deleted a
    whole view.
    """
    _open_work(app_page)
    app_page.locator('[data-testid="lens-beschluesse"]').click()
    expect(
        app_page.locator(".decision-list, .empty-state-title").first
    ).to_be_visible(timeout=10000)


# --------------------------------------------------------------------------- #
# Filtering
# --------------------------------------------------------------------------- #


def test_the_kind_filter_narrows_to_one_former_tab(app_page: Page) -> None:
    """The old split is still reachable — as a filter, not as navigation."""
    _open_work(app_page)
    app_page.locator('[data-testid="work-filter-kind"]').select_option("termin")
    app_page.wait_for_timeout(300)
    kinds = {k.strip() for k in app_page.locator(".kind-chip").all_inner_texts()}
    assert kinds == {"Termin"}


def test_search_filters_across_both_sources(app_page: Page) -> None:
    _open_work(app_page)
    before = app_page.locator(".kind-chip").count()
    app_page.locator('[data-testid="work-search"]').fill("zzz-nichts-passt-zzz")
    app_page.wait_for_timeout(300)
    assert app_page.locator(".kind-chip").count() < before


def test_the_merged_screen_raises_no_console_errors(page: Page) -> None:
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(BASE_URL)
    page.wait_for_selector(".stat-tile", timeout=15000)
    _open_work(page)
    for lens in ("lens-zeitstrahl", "lens-beschluesse", "lens-liste"):
        page.locator(f'[data-testid="{lens}"]').click()
        page.wait_for_timeout(400)

    assert errors == []


def test_the_list_still_shows_todo_priority(app_page: Page) -> None:
    """The merge must not quietly drop a column the old tab had.

    137 of 146 to-dos carry no date, so priority is the only thing left to
    triage them by — a merged list without it would be worse than the tab it
    replaced. The first version of this screen did drop it, caught by an
    older test that asserted a created to-do's priority shows up in its row.
    """
    _open_work(app_page)
    app_page.locator('[data-testid="work-filter-kind"]').select_option("todo")
    app_page.wait_for_timeout(400)
    assert app_page.locator(".prio-dot").count() > 0
