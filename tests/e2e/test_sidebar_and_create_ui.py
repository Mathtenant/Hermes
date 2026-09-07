"""E2E browser tests for the sidebar order, the rename, and the create dialog.

Requires Playwright and a live server on http://localhost:8000; the module
skips cleanly when either is missing.
"""

from __future__ import annotations

import json
import socket
from datetime import date, timedelta

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


def _wait_for_data(page: Page) -> None:
    """Wait until the sidebar exists AND the dashboard fetch has rendered.

    The app used to land on Overview, so waiting for ".stat-tile" happened to
    prove both. It now lands on Planung's timeline, which has neither stat
    tiles nor the list's search box — and ".nav-btn" alone appears before any
    data arrives, so a test reading a count badge immediately after would read
    0 and compare it against a populated one.
    """
    page.wait_for_selector(".nav-btn", timeout=10000)
    # Not "a badge has text": an unloaded badge renders "0", which is text, so
    # that check passes on exactly the state it is meant to exclude. Wait for
    # something the landing screen only renders once rows exist — the timeline
    # track, or the empty state if the database really is empty.
    page.wait_for_selector('.gantt, .empty-state-title', timeout=15000)


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
    _wait_for_data(page)
    page.evaluate("try{localStorage.removeItem('hermes-nav-order')}catch(e){}")
    page.reload()
    _wait_for_data(page)
    return page


def _nav(page: Page) -> list[str]:
    return [t.strip() for t in page.locator(".nav-btn span:nth-child(2)").all_text_contents()]


# --------------------------------------------------------------------------- #
# Rename
# --------------------------------------------------------------------------- #


def test_the_sidebar_never_says_pendenzen(app_page: Page):
    """The word the rename removed must not come back on any route.

    The tab it used to name has since been merged into "Planung",
    so this no longer asserts a "Todo" entry — see test_work_screen_ui.py for
    the merged screen's own contract. What stays worth pinning is the absence.
    """
    assert "Pendenzen" not in _nav(app_page)


def test_the_overview_hero_says_todo(app_page: Page):
    """Overview is no longer the landing screen, so navigate to it first."""
    app_page.click('[data-testid="nav-overview"]')
    app_page.wait_for_selector(".hero-label", timeout=10000)
    assert "Todo" in app_page.locator(".hero-label").inner_text()


def test_the_old_route_key_still_resolves(app_page: Page):
    """This used to assert the hash key never changes. It does now.

    Merging the two tabs replaced #/pendenzen with #/work, so the promise
    that survives is the one that actually matters to a person with a
    bookmark: the old key still lands on the right screen.
    """
    app_page.goto(f"{BASE_URL}/#/pendenzen")
    app_page.wait_for_selector('[data-testid="lens-liste"]', timeout=15000)


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
    app_page.wait_for_selector(".nav-btn", timeout=10000)
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
    bound to screens rather than positions.

    The digit is derived from the shipped order rather than written in: this
    test hard-coded "6" and broke the moment two screens merged into one, for
    a reason that had nothing to do with what it was testing.
    """
    canonical = _nav(app_page)
    digit = str(canonical.index("Risks") + 1)

    app_page.locator('[data-testid="nav-risks"]').focus()
    app_page.keyboard.press("Alt+ArrowUp")
    app_page.wait_for_timeout(300)
    app_page.locator("body").click()
    app_page.keyboard.press(digit)
    app_page.wait_for_timeout(500)
    assert app_page.locator(".page-title").inner_text().strip() == "Risks"


def test_an_unknown_stored_key_is_ignored(app_page: Page):
    """A screen removed in a later version must not leave a hole, and one
    added must not vanish."""
    canonical = _nav(app_page)
    app_page.evaluate(
        "localStorage.setItem('hermes-nav-order',"
        " JSON.stringify(['risks','gibt-es-nicht','overview']))"
    )
    app_page.reload()
    app_page.wait_for_selector(".nav-btn", timeout=10000)
    nav = _nav(app_page)
    assert nav[0] == "Risks"          # stored order honoured
    assert nav[1] == "Overview"
    # Screens absent from the stored list survive, and the bogus key is
    # dropped — compared against the shipped set rather than a written-in
    # count, so merging or adding a screen does not falsify this test.
    assert set(nav) == set(canonical)
    assert len(nav) == len(canonical)


def test_corrupt_stored_order_falls_back_to_the_default(app_page: Page):
    canonical = _nav(app_page)
    app_page.evaluate("localStorage.setItem('hermes-nav-order','not json')")
    app_page.reload()
    app_page.wait_for_selector(".nav-btn", timeout=10000)
    assert _nav(app_page) == canonical


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
    before = int(app_page.locator('[data-testid="nav-work"] .nav-count').inner_text())
    _open_create(app_page)
    app_page.fill('[data-testid="create-title"]', "E2E Neuer Punkt")
    app_page.fill('[data-testid="create-owner"]', "E2E Owner")
    app_page.select_option('[data-testid="create-priority"]', "high")
    app_page.click('[data-testid="create-submit"]')
    app_page.wait_for_timeout(2500)

    after = int(app_page.locator('[data-testid="nav-work"] .nav-count').inner_text())
    assert after == before + 1

    app_page.click('[data-testid="nav-work"]')
    # Planung opens on the timeline; the search box lives on the list lens.
    app_page.locator('[data-testid="lens-liste"]').click()
    app_page.fill('[data-testid="work-search"]', "E2E Neuer Punkt")
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


# --------------------------------------------------------------------------- #
# Frist
#
# A bare date input asks "which day?" when the question in someone's head is
# "how soon?". Three quick answers plus a calendar for the rest — and, because
# Planung now opens on the timeline, a to-do given a deadline has to actually
# turn up there.
# --------------------------------------------------------------------------- #


def _friday_of_this_week() -> str:
    """Friday of the current working week; on Sat/Sun, the coming Friday.

    Computed here rather than read back from the page, so the test disagrees
    with the implementation when the implementation is wrong.
    """
    today = date.today()
    dow = today.weekday()                       # Mon = 0
    delta = 4 - dow if dow <= 4 else 11 - dow
    return (today + timedelta(days=delta)).isoformat()


def test_the_dialog_asks_how_soon_before_which_day(app_page: Page):
    _open_create(app_page)
    presets = app_page.locator('[data-testid="create-due-presets"] button')
    assert [p.strip() for p in presets.all_text_contents()] == [
        "Ohne", "Heute", "Diese Woche", "Datum …",
    ]


def test_no_deadline_is_the_default_and_says_what_it_costs(app_page: Page):
    """Inventing a date nobody set would put a false bar on the timeline and,
    a week later, a false overdue count."""
    _open_create(app_page)
    assert app_page.locator('[data-testid="create-due-none"]').get_attribute(
        "aria-pressed"
    ) == "true"
    hint = app_page.locator('[data-testid="create-due-hint"]').inner_text()
    assert "Zeitstrahl" in hint
    # The calendar stays out of the way until it is asked for.
    assert app_page.locator('[data-testid="create-due"]').count() == 0


def test_heute_resolves_to_todays_date(app_page: Page):
    _open_create(app_page)
    app_page.click('[data-testid="create-due-today"]')
    shown = app_page.locator('[data-testid="create-due-resolved"]').inner_text()
    d, m, y = date.today().isoformat().split("-")[::-1]
    assert f"{d}.{m}.{y}" in shown


def test_diese_woche_resolves_to_friday(app_page: Page):
    """Friday, not Sunday: a deadline landing on a weekend is one nobody
    is going to meet anyway."""
    _open_create(app_page)
    app_page.click('[data-testid="create-due-week"]')
    shown = app_page.locator('[data-testid="create-due-resolved"]').inner_text()
    d, m, y = _friday_of_this_week().split("-")[::-1]
    assert f"{d}.{m}.{y}" in shown


def test_datum_opens_a_calendar(app_page: Page):
    _open_create(app_page)
    app_page.click('[data-testid="create-due-date"]')
    assert app_page.locator('[data-testid="create-due"]').is_visible()
    assert app_page.locator('[data-testid="create-due-resolved"]').count() == 0


def test_a_picked_date_survives_a_detour_through_the_presets(app_page: Page):
    """Clicking away and back must not silently drop a date already chosen."""
    _open_create(app_page)
    app_page.click('[data-testid="create-due-date"]')
    app_page.fill('[data-testid="create-due"]', "2027-04-01")
    app_page.click('[data-testid="create-due-today"]')
    app_page.click('[data-testid="create-due-date"]')
    assert app_page.locator('[data-testid="create-due"]').input_value() == "2027-04-01"


def test_a_todo_with_a_deadline_lands_on_the_timeline(app_page: Page):
    """The screen opens on the timeline, so this is where the reader looks.

    The Gantt reads only what a sweep imported, which was invisible while the
    list was the landing lens — a to-do you just gave a deadline to would not
    have been on the one screen you would go looking for it.
    """
    title = "E2E Frist heute"
    _open_create(app_page)
    app_page.fill('[data-testid="create-title"]', title)
    app_page.click('[data-testid="create-due-today"]')
    app_page.click('[data-testid="create-submit"]')
    app_page.wait_for_timeout(2500)

    app_page.click('[data-testid="nav-work"]')
    app_page.wait_for_selector(".gantt", timeout=10000)
    app_page.wait_for_timeout(600)
    rows = [t.strip() for t in app_page.locator(".gantt-row-title").all_text_contents()]
    assert title in rows, rows[:8]


def test_a_todo_without_a_deadline_stays_off_the_timeline(app_page: Page):
    """The hint promises exactly this, and the undated notice covers it."""
    title = "E2E Ohne Frist"
    _open_create(app_page)
    app_page.fill('[data-testid="create-title"]', title)
    app_page.click('[data-testid="create-submit"]')
    app_page.wait_for_timeout(2500)

    app_page.click('[data-testid="nav-work"]')
    app_page.wait_for_selector(".gantt", timeout=10000)
    app_page.wait_for_timeout(600)
    rows = [t.strip() for t in app_page.locator(".gantt-row-title").all_text_contents()]
    assert title not in rows

    app_page.locator('[data-testid="lens-liste"]').click()
    app_page.fill('[data-testid="work-search"]', title)
    app_page.wait_for_timeout(500)
    assert app_page.locator(f'tbody tr:has-text("{title}")').count() > 0


# --------------------------------------------------------------------------- #
# Smart capture
#
# The model is routed here rather than run: Ollama is not up in CI, and a test
# that silently skips when it is missing is not a test. What the browser has to
# prove is what the browser owns — that an answer reaches the right fields, and
# that a model which is not there leaves a dialog somebody can still use.
# --------------------------------------------------------------------------- #


def _route_capture(page: Page, status: int, body: str) -> None:
    page.route(
        "**/api/todos/parse",
        lambda route: route.fulfill(
            status=status, content_type="application/json", body=body
        ),
    )


def test_a_sentence_fills_every_field(app_page: Page):
    _route_capture(app_page, 200, json.dumps({
        "title": "Rechnung Lieferant X pruefen",
        "owner": "Controlling",
        "priority": "blocker",
        "due_date": "2027-09-10",
        "model": "qwen3:4b",
    }))
    _open_create(app_page)
    app_page.fill('[data-testid="capture-input"]', "Rechnung bis Freitag, Controlling")
    app_page.click('[data-testid="capture-submit"]')
    app_page.wait_for_selector('[data-testid="capture-note"]', timeout=8000)

    assert app_page.locator('[data-testid="create-title"]').input_value() == (
        "Rechnung Lieferant X pruefen"
    )
    assert app_page.locator('[data-testid="create-owner"]').input_value() == "Controlling"
    assert app_page.locator('[data-testid="create-priority"]').input_value() == "blocker"
    # A returned date has to reach the Frist control, not just the hidden input:
    # leaving the preset on "Ohne" would submit no deadline at all.
    assert app_page.locator('[data-testid="create-due-date"]').get_attribute(
        "aria-pressed"
    ) == "true"
    assert app_page.locator('[data-testid="create-due"]').input_value() == "2027-09-10"


def test_the_answer_names_the_model_that_gave_it(app_page: Page):
    """Worth knowing which model read the sentence, when it read it badly."""
    _route_capture(app_page, 200, json.dumps({
        "title": "x", "owner": "", "priority": "medium",
        "due_date": "", "model": "qwen3:4b",
    }))
    _open_create(app_page)
    app_page.fill('[data-testid="capture-input"]', "irgendwas")
    app_page.click('[data-testid="capture-submit"]')
    app_page.wait_for_selector('[data-testid="capture-note"]', timeout=8000)
    assert "qwen3:4b" in app_page.locator('[data-testid="capture-note"]').inner_text()


def test_an_empty_title_falls_back_to_what_was_typed(app_page: Page):
    """A model that returns nothing should leave the person their own words,
    not an empty form."""
    _route_capture(app_page, 200, json.dumps({
        "title": "", "owner": "", "priority": "medium",
        "due_date": "", "model": "qwen3:4b",
    }))
    _open_create(app_page)
    app_page.fill('[data-testid="capture-input"]', "Vertrag kuendigen")
    app_page.click('[data-testid="capture-submit"]')
    app_page.wait_for_selector('[data-testid="capture-note"]', timeout=8000)
    assert app_page.locator('[data-testid="create-title"]').input_value() == (
        "Vertrag kuendigen"
    )


def test_an_unreachable_model_leaves_a_usable_dialog(app_page: Page):
    """The feature is a shortcut, never a dependency."""
    _route_capture(app_page, 503, json.dumps({
        "detail": "Kein lokales Modell erreichbar — bitte Felder von Hand füllen."
    }))
    _open_create(app_page)
    app_page.fill('[data-testid="capture-input"]', "irgendwas")
    app_page.click('[data-testid="capture-submit"]')
    app_page.wait_for_selector('[data-testid="capture-error"]', timeout=8000)

    assert "von Hand" in app_page.locator('[data-testid="capture-error"]').inner_text()
    # And the form still works by hand.
    app_page.fill('[data-testid="create-title"]', "Von Hand getippt")
    assert app_page.locator('[data-testid="create-submit"]').is_enabled()


def test_the_button_is_dead_until_something_is_typed(app_page: Page):
    _open_create(app_page)
    assert app_page.locator('[data-testid="capture-submit"]').is_disabled()
    app_page.fill('[data-testid="capture-input"]', "x")
    assert app_page.locator('[data-testid="capture-submit"]').is_enabled()


def test_capture_is_offered_for_todos_only(app_page: Page):
    """A work-breakdown node or a project directory is not the thing anyone
    types in one hurried sentence mid-meeting."""
    _open_create(app_page)
    assert app_page.locator('[data-testid="capture-input"]').count() == 1
    app_page.click('[data-testid="create-kind-task"]')
    assert app_page.locator('[data-testid="capture-input"]').count() == 0
    app_page.click('[data-testid="create-kind-project"]')
    assert app_page.locator('[data-testid="capture-input"]').count() == 0
