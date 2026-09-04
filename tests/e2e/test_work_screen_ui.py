"""E2E browser tests for the merged "Planung" screen.

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
    page.wait_for_selector(".nav-btn", timeout=15000)
    page.evaluate("try{localStorage.removeItem('hermes-nav-order')}catch(e){}")
    page.reload()
    page.wait_for_selector(".nav-btn", timeout=15000)
    return page


def _nav(page: Page) -> list[str]:
    return [
        t.strip().split("\n")[0]
        for t in page.locator(".nav-btn span:nth-child(2)").all_text_contents()
    ]


def _open_work(page: Page) -> None:
    """Open Planung on the LIST lens.

    The screen opens on the timeline now, so "open the screen" and "look at
    the list" stopped being the same act. Every caller below was written
    against the list, so the switch lives here rather than in forty places.
    """
    page.get_by_role("button", name="Planung").first.click()
    page.wait_for_selector('[data-testid="lens-liste"]', timeout=10000)
    page.locator('[data-testid="lens-liste"]').click()
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
    assert "Planung" in _nav(app_page)


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
        '.nav-btn:has-text("Planung") .nav-count'
    ).first
    assert badge.inner_text().strip() == str(counts)


# --------------------------------------------------------------------------- #
# Nothing gets stranded
# --------------------------------------------------------------------------- #


def test_an_old_pendenzen_bookmark_still_lands_somewhere(page: Page) -> None:
    """A retired key must forward, not fall through to the default screen."""
    page.goto(f"{BASE_URL}/#/pendenzen")
    page.wait_for_selector('[data-testid="lens-liste"]', timeout=15000)
    expect(page.locator('[data-testid="lens-liste"]')).to_be_visible()


def test_an_old_plan_bookmark_still_lands_somewhere(page: Page) -> None:
    page.goto(f"{BASE_URL}/#/plan")
    page.wait_for_selector('[data-testid="lens-liste"]', timeout=15000)
    expect(page.locator('[data-testid="lens-liste"]')).to_be_visible()


def test_a_stored_order_with_retired_keys_keeps_its_slot(page: Page) -> None:
    """The merged tab inherits its predecessor's position.

    Treating it as brand new would append it to the bottom of a sidebar
    somebody deliberately arranged.
    """
    page.goto(BASE_URL)
    page.wait_for_selector(".nav-btn", timeout=15000)
    page.evaluate(
        """() => localStorage.setItem('hermes-nav-order', JSON.stringify(
            ['pendenzen', 'overview', 'projects', 'detail', 'plan',
             'risks', 'reviews']))"""
    )
    page.reload()
    page.wait_for_selector(".nav-btn", timeout=15000)

    assert _nav(page)[0] == "Planung"


def test_a_stored_order_naming_both_retired_keys_yields_one_tab(page: Page) -> None:
    """Two old keys map to one new one, so the result must not duplicate it."""
    page.goto(BASE_URL)
    page.wait_for_selector(".nav-btn", timeout=15000)
    page.evaluate(
        """() => localStorage.setItem('hermes-nav-order', JSON.stringify(
            ['plan', 'pendenzen', 'overview', 'projects', 'detail',
             'risks', 'reviews']))"""
    )
    page.reload()
    page.wait_for_selector(".nav-btn", timeout=15000)

    nav = _nav(page)
    assert nav.count("Planung") == 1


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
    page.wait_for_selector(".nav-btn", timeout=15000)
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


# --------------------------------------------------------------------------- #
# Landing page
# --------------------------------------------------------------------------- #


def test_the_dashboard_opens_on_planung(page: Page) -> None:
    """The first question on opening is "what do I owe, and by when".

    Overview only summarised the answer and sent you one click further to
    read it.
    """
    page.goto(BASE_URL)
    page.wait_for_selector('[data-testid="lens-liste"]', timeout=15000)
    assert page.url.endswith("#/work")


def test_the_dashboard_opens_on_the_timeline_lens(page: Page) -> None:
    """"What is coming" is a shape, not a list.

    The list was the default while it was the only lens that could show every
    item; the count notice above the track covers what the timeline leaves
    out, and links to the list for the rest.
    """
    page.goto(BASE_URL)
    page.wait_for_selector(".gantt", timeout=15000)
    expect(page.locator('[data-testid="lens-zeitstrahl"]')).to_have_attribute(
        "aria-selected", "true"
    )


# --------------------------------------------------------------------------- #
# Timeline: today-sync and time-scale zoom
# --------------------------------------------------------------------------- #


def _open_timeline(page: Page) -> None:
    page.get_by_role("button", name="Planung").first.click()
    page.wait_for_selector('[data-testid="lens-zeitstrahl"]', timeout=10000)
    page.locator('[data-testid="lens-zeitstrahl"]').click()
    page.wait_for_selector(".gantt", timeout=10000)
    page.wait_for_timeout(700)


def test_the_timeline_marks_today(app_page: Page) -> None:
    """The domain always contains today, so the anchor is always drawable.

    A plan whose every dated item is in the future used to render no marker
    at all — exactly when knowing where "now" sits matters most.
    """
    _open_timeline(app_page)
    assert app_page.locator(".gantt-today").count() == 1


def test_the_timeline_opens_on_today(app_page: Page) -> None:
    """Otherwise a zoomed track opens at the project start, months away.

    This asked for today near the *centre*, which was right while the axis
    still reached into the past. It starts on today now, so the marker sits at
    the left edge by construction and centring is not a promise anyone can
    keep. What survives — and is what the test was ever really for — is that
    the marker is on screen when the plan opens, at any zoom.
    """
    _open_timeline(app_page)
    scroller = app_page.locator(".gantt-scroll").first
    for scale in ("monat", "woche", "tag"):
        app_page.locator('[data-testid="zoom-level"]').select_option(scale)
        app_page.wait_for_timeout(600)
        marker = app_page.locator(".gantt-today").first.bounding_box()
        view = scroller.bounding_box()
        assert view["x"] <= marker["x"] <= view["x"] + view["width"], (
            f"today is off screen at scale {scale}"
        )


@pytest.mark.parametrize(
    ("scale", "sample"),
    [("tag", None), ("woche", "KW"), ("monat", None), ("quartal", "Q"), ("jahr", None)],
)
def test_each_scale_labels_its_own_unit(app_page: Page, scale, sample) -> None:
    """The old zoom scaled the bars and left the axis in months at every step.

    Zooming in then told you nothing new, which is what made it useless.
    """
    _open_timeline(app_page)
    app_page.locator('[data-testid="zoom-level"]').select_option(scale)
    app_page.wait_for_timeout(500)
    labels = app_page.locator(".gantt-tick-label").all_inner_texts()
    assert labels, f"{scale} produced no axis labels at all"
    if sample:
        assert any(sample in t for t in labels), (scale, labels[:5])


def test_zooming_in_narrows_the_time_unit(app_page: Page) -> None:
    _open_timeline(app_page)
    app_page.locator('[data-testid="zoom-level"]').select_option("monat")
    app_page.wait_for_timeout(400)
    app_page.locator('[data-testid="zoom-in"]').click()
    app_page.wait_for_timeout(400)
    assert app_page.locator('[data-testid="zoom-level"]').input_value() == "woche"


def test_zooming_in_widens_the_track(app_page: Page) -> None:
    """A finer scale must give each day more room, not just relabel."""
    _open_timeline(app_page)
    app_page.locator('[data-testid="zoom-level"]').select_option("monat")
    app_page.wait_for_timeout(400)
    narrow = app_page.locator(".gantt").first.evaluate("e => e.scrollWidth")
    app_page.locator('[data-testid="zoom-level"]').select_option("woche")
    app_page.wait_for_timeout(500)
    wide = app_page.locator(".gantt").first.evaluate("e => e.scrollWidth")
    assert wide > narrow


def test_zoom_is_bounded_at_both_ends(app_page: Page) -> None:
    """The end buttons disable rather than wrapping around or no-oping.

    Written as "click while enabled": clicking a disabled button makes
    Playwright wait for it to become enabled, so a fixed-count loop hangs on
    exactly the correct behaviour it is checking for.
    """
    _open_timeline(app_page)
    level = app_page.locator('[data-testid="zoom-level"]')

    zoom_in = app_page.locator('[data-testid="zoom-in"]')
    for _ in range(8):
        if zoom_in.is_disabled():
            break
        zoom_in.click()
        app_page.wait_for_timeout(150)
    assert level.input_value() == "tag"
    assert zoom_in.is_disabled()

    zoom_out = app_page.locator('[data-testid="zoom-out"]')
    for _ in range(8):
        if zoom_out.is_disabled():
            break
        zoom_out.click()
        app_page.wait_for_timeout(150)
    assert level.input_value() == "jahr"
    assert zoom_out.is_disabled()


def test_the_today_button_brings_the_view_back(app_page: Page) -> None:
    """Scroll away, press Heute, land back on today.

    This used to scroll to 0 and assert the button moved the view right, back
    to a today sitting somewhere in the middle. Today is the LEFT EDGE of the
    axis now, so that test asserted the button could not do its job. Pan away
    first and check the marker is on screen afterwards — which is the promise,
    whatever position it happens to correspond to.
    """
    _open_timeline(app_page)
    app_page.locator('[data-testid="zoom-level"]').select_option("tag")
    app_page.wait_for_timeout(600)
    scroller = app_page.locator(".gantt-scroll").first
    scroller.evaluate("e => { e.scrollLeft = 900; }")
    app_page.wait_for_timeout(200)
    assert scroller.evaluate("e => e.scrollLeft") > 0, "could not pan away"

    app_page.locator('[data-testid="jump-today"]').click()
    app_page.wait_for_timeout(500)

    marker = app_page.locator(".gantt-today").first.bounding_box()
    view = scroller.bounding_box()
    assert view["x"] <= marker["x"] <= view["x"] + view["width"], (
        "the Heute marker is not in view after pressing Heute"
    )


# --------------------------------------------------------------------------- #
# Multi-select owner filter
# --------------------------------------------------------------------------- #


def test_several_owners_can_be_selected_at_once(app_page: Page) -> None:
    """"What is on Meier and Brunner" was two passes over the same screen."""
    _open_work(app_page)
    app_page.locator('[data-testid="work-filter-owner"] summary').click()
    options = app_page.locator('[data-testid="work-owner-option"]')
    if options.count() < 2:
        pytest.skip("needs at least two owners in the data")

    options.nth(0).check()
    app_page.wait_for_timeout(250)
    one = app_page.locator(".kind-chip").count()
    options.nth(1).check()
    app_page.wait_for_timeout(350)
    two = app_page.locator(".kind-chip").count()

    # OR-ed, so adding a name can only widen the result.
    assert two >= one


def test_the_filter_button_reports_how_many_are_picked(app_page: Page) -> None:
    _open_work(app_page)
    summary = app_page.locator('[data-testid="work-filter-owner"] summary')
    assert "Alle" in summary.inner_text()

    summary.click()
    options = app_page.locator('[data-testid="work-owner-option"]')
    if options.count() < 2:
        pytest.skip("needs at least two owners in the data")
    options.nth(0).check()
    options.nth(1).check()
    app_page.wait_for_timeout(300)

    assert "2 Verantwortliche" in summary.inner_text()


def test_clearing_the_owner_selection_restores_everything(app_page: Page) -> None:
    """An empty selection means "everyone", not "nobody"."""
    _open_work(app_page)
    all_rows = app_page.locator(".kind-chip").count()

    app_page.locator('[data-testid="work-filter-owner"] summary').click()
    options = app_page.locator('[data-testid="work-owner-option"]')
    if not options.count():
        pytest.skip("needs at least one owner in the data")
    options.nth(0).check()
    app_page.wait_for_timeout(300)
    assert app_page.locator(".kind-chip").count() < all_rows

    app_page.locator('[data-testid="work-owner-clear"]').click()
    app_page.wait_for_timeout(300)
    assert app_page.locator(".kind-chip").count() == all_rows


# --------------------------------------------------------------------------- #
# The default time window
#
# The timeline used to open three months BACK, so a plan presented a wall of
# finished green bars with today pushed off the right-hand edge. "Ab heute" is
# not "hide everything before today", though: an overdue item is in the past
# and is the most urgent row on the board.
# --------------------------------------------------------------------------- #


def test_the_timeline_opens_from_today_not_months_back(app_page: Page) -> None:
    _open_timeline(app_page)
    window = app_page.locator('select[aria-label="Zeitraum"]')
    assert window.input_value() == "heute"


def test_finished_past_work_is_not_shown_by_default(app_page: Page) -> None:
    """Months of completed bars are exactly what nobody needs to re-read."""
    _open_timeline(app_page)
    statuses = app_page.locator(".gantt-row .chip").all_inner_texts()
    assert "Erledigt" not in [s.strip() for s in statuses]


def test_overdue_work_survives_the_default_window(app_page: Page) -> None:
    """The one thing "from today" must NOT drop.

    An overdue item is dated in the past and is the most relevant row there
    is; filtering purely by date would hide it.
    """
    _open_timeline(app_page)
    today = app_page.evaluate("() => new Date().toISOString().slice(0, 10)")
    overdue = app_page.evaluate(
        """async (today) => {
            const r = await fetch('/api/dashboard');
            const d = await r.json();
            return d.ablaufplan.filter(
                x => (x.end || '') < today && x.status !== 'erledigt'
            ).map(x => x.title);
        }""",
        today,
    )
    if not overdue:
        pytest.skip("no overdue rows in the data")
    shown = " ".join(app_page.locator(".gantt-row").all_inner_texts())
    for title in overdue:
        assert title[:25] in shown, f"overdue row hidden: {title}"


def test_a_far_future_outlier_does_not_stretch_the_axis(app_page: Page) -> None:
    """One typo'd year must not squeeze every real bar into a few pixels.

    Removing the forward bound to get "from today" did exactly that: a 2099
    date in the data ran the axis out to 2059 and made the track 213,000 px
    wide. The forward window stays bounded.
    """
    _open_timeline(app_page)
    labels = app_page.locator(".gantt-tick-label").all_inner_texts()
    years = [int(t) for label in labels for t in [label[-4:]] if t.isdigit()]
    this_year = int(app_page.evaluate("() => new Date().getUTCFullYear()"))
    assert all(y <= this_year + 3 for y in years), labels[-5:]

    width = app_page.locator(".gantt").first.evaluate("e => e.scrollWidth")
    assert width < 20000, f"track is {width}px wide"


def test_what_the_window_hides_is_stated_not_silent(app_page: Page) -> None:
    """A filter that quietly drops rows is worse than no filter."""
    _open_timeline(app_page)
    hidden = app_page.locator("text=ausserhalb des gewählten Zeitraums")
    if not hidden.count():
        pytest.skip("nothing outside the window in this data")
    assert app_page.locator("text=Ganzen Zeitraum zeigen").count() == 1


def test_the_whole_span_is_still_reachable(app_page: Page) -> None:
    _open_timeline(app_page)
    before = app_page.locator(".gantt-row").count()
    app_page.locator('select[aria-label="Zeitraum"]').select_option("all")
    app_page.wait_for_timeout(600)
    assert app_page.locator(".gantt-row").count() > before


# --------------------------------------------------------------------------- #
# The axis extent
#
# Selecting rows and sizing the axis are two different jobs, and only the first
# was respecting the window. One overdue bar that STARTED on 1 July is rightly
# kept — it is not finished — but its start date dragged the whole axis back
# two months, so the plan opened on Jun/Jul/Aug with today squeezed right.
# --------------------------------------------------------------------------- #


def test_the_axis_starts_on_today_and_not_a_day_earlier(app_page: Page) -> None:
    """The earliest date on the ruler is today. No past months, at all.

    This used to allow the month before, so the axis could reach back to the
    oldest overdue deadline and give an already-ended bar somewhere to draw.
    One bar's lane is not worth putting July on a September plan; those bars
    are stubs against the edge now (see the is-past tests below).
    """
    _open_timeline(app_page)
    assert app_page.locator(".gantt-bar, .gantt-milestone, .gantt-termin").count() > 0

    month = app_page.evaluate("() => new Date().getUTCMonth()")
    first = app_page.locator(".gantt-tick-label").first.inner_text()
    months = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
              "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]
    assert months.index(first.strip()[:3]) == month, (
        f"axis opens at {first}, but today is {months[month]}"
    )


def test_the_day_scale_opens_on_todays_date(app_page: Page) -> None:
    """The month name is coarse enough to hide an off-by-a-week start."""
    _open_timeline(app_page)
    app_page.locator('[data-testid="zoom-level"]').select_option("tag")
    app_page.wait_for_timeout(700)
    first = app_page.locator(".gantt-tick-label").first.inner_text().strip()
    today = app_page.evaluate("() => new Date().getUTCDate()")
    assert first == str(today), f"day axis opens on {first}, today is {today}"


def test_the_first_stretch_of_the_axis_is_labelled(app_page: Page) -> None:
    """An axis starting mid-month must still name the month it starts in.

    Ticks land on month boundaries, so an axis beginning on the 4th had its
    first label at 1 October — the weeks the reader is actually standing in
    went unnamed, and the plan appeared to open in the wrong month.
    """
    _open_timeline(app_page)
    first = app_page.locator(".gantt-tick-label").first
    left = first.evaluate("e => parseFloat(e.style.left) || 0")
    assert left < 4, f"first axis label sits {left}% in, leaving a blank run"


def test_a_long_running_bar_is_clipped_not_axis_stretching(app_page: Page) -> None:
    """A bar that began before the window is cut at the edge.

    The alternative — letting it widen the axis — is what put June on screen.
    """
    _open_timeline(app_page)
    clipped = app_page.locator(".gantt-bar.is-clipped")
    if not clipped.count():
        pytest.skip("no bar starts before the window in this data")
    style = clipped.first.get_attribute("style") or ""
    assert "left: 0%" in style


def test_an_item_whose_deadline_has_passed_is_pinned_to_the_edge(app_page: Page) -> None:
    """It ended before the window, so it has no place on the ruler — but it is
    on screen because it is overdue and open, and an empty lane hides exactly
    the finding the reader came for."""
    _open_timeline(app_page)
    past = app_page.locator(".is-past")
    if not past.count():
        pytest.skip("nothing overdue-and-ended in this data")
    for i in range(past.count()):
        style = past.nth(i).get_attribute("style") or ""
        assert "left: 0%" in style, f"is-past mark not at the edge: {style}"
        assert past.nth(i).is_visible()


def test_a_past_bar_is_told_apart_from_one_starting_today(app_page: Page) -> None:
    """Both sit at x=0. Only the class and the label say which is which."""
    _open_timeline(app_page)
    bar = app_page.locator(".gantt-bar.is-past").first
    if not bar.count():
        pytest.skip("no fully-past bar in this data")
    assert "verstrichen" in (bar.get_attribute("aria-label") or "")


def test_every_visible_row_draws_something(app_page: Page) -> None:
    """An overdue row with no mark is worse than the problem being fixed.

    Clamping the axis to today made an overdue bar that had also ENDED before
    today render as an empty lane: listed, correctly, with nothing in it. The
    axis stays clamped — those bars are drawn as stubs at the edge instead.
    """
    _open_timeline(app_page)
    rows = app_page.locator(".gantt-row")
    assert rows.count() > 0
    for i in range(rows.count()):
        row = rows.nth(i)
        marks = row.locator(".gantt-bar, .gantt-milestone, .gantt-termin")
        visible = any(marks.nth(j).is_visible() for j in range(marks.count()))
        label = row.inner_text().split("\n")[0][:40]
        assert visible, f"row draws nothing: {label}"


# --------------------------------------------------------------------------- #
# Drag to pan
# --------------------------------------------------------------------------- #


def _wide_timeline(page: Page):
    """A timeline zoomed far enough in that the track overflows."""
    _open_timeline(page)
    page.locator('[data-testid="zoom-level"]').select_option("woche")
    # setScale() re-centres asynchronously; read scrollLeft before that settles
    # and the drag is measured against a moving target.
    page.wait_for_timeout(800)
    scroller = page.locator(".gantt-scroll").first
    dims = scroller.evaluate("e => ({sw: e.scrollWidth, cw: e.clientWidth})")
    if dims["sw"] <= dims["cw"]:
        pytest.skip("track fits; nothing to pan")
    return scroller


def _grab_points(page: Page, scroller) -> tuple[float, float, float]:
    """Two x's and a y at which a press really lands on the track.

    Fixed offsets from the scroller's own box are not enough: the chat widget
    floats over the bottom-right of the viewport, so (box.x + 800, box.y + 150)
    presses its input instead — the pan handler never fires and the test fails
    for a reason that has nothing to do with panning. Ask the document what is
    actually on top before deciding where to grab.
    """
    # elementFromPoint is viewport-relative and returns null off-screen, so a
    # track sitting below the fold would look "obstructed" everywhere.
    scroller.scroll_into_view_if_needed()
    page.wait_for_timeout(200)
    box = scroller.bounding_box()
    probe = """([bx, by, bw, dy]) => {
      const xs = [];
      for (let dx = 40; dx < bw - 20; dx += 20) {
        const el = document.elementFromPoint(bx + dx, by + dy);
        if (el && el.closest('.gantt-track-col') && !el.closest('button, input, select, a')) {
          xs.push(dx);
        }
      }
      return xs;
    }"""
    for dy in (40, 60, 90, 120, 150, 200):
        xs = page.evaluate(probe, [box["x"], box["y"], box["width"], dy])
        if len(xs) >= 2 and xs[-1] - xs[0] >= 200:
            return box["x"] + xs[-1], box["x"] + xs[0], box["y"] + dy
    pytest.skip("no unobstructed stretch of track to grab")


def _drag(page: Page, x_from: float, x_to: float, y: float) -> None:
    page.mouse.move(x_from, y)
    page.mouse.down()
    page.mouse.move(x_to, y, steps=12)
    page.mouse.up()
    page.wait_for_timeout(250)


def test_dragging_the_track_pans_it(app_page: Page) -> None:
    """Grabbing and dragging is what everyone tries first on a timeline."""
    scroller = _wide_timeline(app_page)
    right, left, y = _grab_points(app_page, scroller)
    before = scroller.evaluate("e => e.scrollLeft")

    _drag(app_page, right, left, y)  # content moves left ⇒ scrollLeft grows

    assert scroller.evaluate("e => e.scrollLeft") > before


def test_dragging_back_returns_the_view(app_page: Page) -> None:
    scroller = _wide_timeline(app_page)
    right, left, y = _grab_points(app_page, scroller)

    _drag(app_page, right, left, y)
    panned = scroller.evaluate("e => e.scrollLeft")

    _drag(app_page, left, right, y)

    assert scroller.evaluate("e => e.scrollLeft") < panned


def test_the_task_names_stay_put_while_the_track_pans(app_page: Page) -> None:
    """A bar with no name beside it says nothing.

    That is the state a scrolled timeline ended in before the label column was
    pinned: pan far enough and every row became an anonymous coloured stripe.
    """
    scroller = _wide_timeline(app_page)
    label = app_page.locator(".gantt-row .gantt-label-col").first
    head = app_page.locator(".gantt-head .gantt-label-col").first
    before = label.bounding_box()["x"]
    head_before = head.bounding_box()["x"]
    text_before = label.inner_text()

    scroller.evaluate("e => { e.scrollLeft = 700; }")
    app_page.wait_for_timeout(300)
    assert scroller.evaluate("e => e.scrollLeft") > 0, "track did not actually pan"

    assert abs(label.bounding_box()["x"] - before) < 1
    assert abs(head.bounding_box()["x"] - head_before) < 1, "the header cell drifted"
    assert label.inner_text() == text_before
    assert label.is_visible()


def test_the_pinned_column_is_opaque(app_page: Page) -> None:
    """Without a background of its own the bars slide visibly under the text."""
    scroller = _wide_timeline(app_page)
    label = app_page.locator(".gantt-row .gantt-label-col").first
    bg = label.evaluate("e => getComputedStyle(e).backgroundColor")
    assert bg not in ("rgba(0, 0, 0, 0)", "transparent"), bg
    assert scroller.evaluate(
        "e => getComputedStyle(e.querySelector('.gantt-label-col')).position"
    ) == "sticky"


def test_a_press_without_movement_leaves_the_view_alone(app_page: Page) -> None:
    """Clicking the track is not a pan — and must not end stuck mid-drag.

    A missed pointerup leaves `is-dragging` latched: the cursor stays "grabbing"
    and text selection stays suppressed for the rest of the session, with
    nothing on screen to explain it.
    """
    scroller = _wide_timeline(app_page)
    _, left, y = _grab_points(app_page, scroller)
    before = scroller.evaluate("e => e.scrollLeft")

    app_page.mouse.move(left, y)
    app_page.mouse.down()
    app_page.mouse.up()
    app_page.wait_for_timeout(200)

    assert scroller.evaluate("e => e.scrollLeft") == before
    assert "is-dragging" not in (scroller.get_attribute("class") or "")
