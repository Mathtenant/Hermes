"""E2E browser tests for the Ablaufplan (Gantt) and Beschlüsse views.

Both render data imported from documents that are near-universal in these
project folders — ``Projektablaufplan_Detail`` and the ``Pendenzen- und
Beschlussliste``. The tests import a known plan through the real API, then
assert on what the browser actually draws.

Requires Playwright and a live server on http://localhost:8000; the module
skips cleanly when either is missing.
"""

from __future__ import annotations

import socket

import pytest

pytest.importorskip("playwright.sync_api")
import urllib.request  # noqa: E402

from playwright.sync_api import Page  # noqa: E402

pytestmark = pytest.mark.e2e

BASE_URL = "http://localhost:8000"

# The plan fixture, expressed in the surviving cross-source schema. Far-future
# dates keep it from colliding with real data; the default time window excludes
# them, so the fixtures select "Ganzer Zeitraum" first.
_ABLAUFPLAN = {
    "schema": "hermes.faelligkeiten/v1",
    "project_ref": "proj/e2e-plan",
    "project_label": "E2E Plan",
    "faelligkeiten": [
        {
            "external_ref": "fk/e2e-konzept-erstellen",
            "titel": "E2E Detailkonzept erstellen",
            "start": "2099-01-05", "faellig_am": "2099-02-20",
            "ebene": "arbeitspaket", "status": "erledigt",
            "verantwortlich": "Fachbereich", "phase": "E2E Konzept",
            "fortschritt_prozent": 100, "quelle": "e2e-ablaufplan.xlsx",
        },
        {
            "external_ref": "fk/e2e-abnahme",
            "titel": "E2E Konzept-Abnahme",
            "faellig_am": "2099-02-20", "ebene": "meilenstein",
            "status": "offen", "phase": "E2E Konzept",
            "quelle": "e2e-ablaufplan.xlsx",
        },
        {
            "external_ref": "fk/e2e-bau-arbeiten",
            "titel": "E2E Realisierung durchführen",
            "start": "2099-02-21", "faellig_am": "2099-06-30",
            "ebene": "arbeitspaket", "status": "laufend",
            "verantwortlich": "IT", "phase": "E2E Realisierung",
            "fortschritt_prozent": 45, "quelle": "e2e-ablaufplan.xlsx",
        },
        {
            "external_ref": "fk/e2e-blockiert",
            "titel": "E2E Blockierter Vorgang",
            "start": "2099-03-01", "faellig_am": "2099-04-15",
            "ebene": "arbeitspaket", "status": "blockiert",
            "phase": "E2E Realisierung", "quelle": "e2e-ablaufplan.xlsx",
        },
    ],
}

_BESCHLUESSE = {
    "schema": "hermes.beschluesse/v1",
    "project_ref": "proj/e2e-plan",
    "beschluesse": [
        {
            "external_ref": "bs/e2e-entscheid",
            "titel": "E2E Verzicht auf Eigenentwicklung",
            "beschlossen_am": "2099-01-15",
            "gremium": "E2E Steuerungsausschuss",
            "status": "beschlossen",
            "betrifft": "E2E Checkout",
        },
    ],
    "pendenzen": [
        {
            "external_ref": "pd/e2e-offen",
            "titel": "E2E Vertrag prüfen",
            "verantwortlich": "Legal", "termin": "2099-03-31",
            "prioritaet": "high", "status": "open",
            "beschluss_ref": "bs/e2e-entscheid",
        },
        {
            "external_ref": "pd/e2e-erledigt",
            "titel": "E2E Lizenzkosten nachführen",
            "status": "closed", "beschluss_ref": "bs/e2e-entscheid",
        },
    ],
}


def _server_up(host: str = "localhost", port: int = 8000) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _post(payload: dict) -> dict:
    import json

    req = urllib.request.Request(
        f"{BASE_URL}/api/import/json",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


@pytest.fixture(scope="module", autouse=True)
def _seeded():
    """Import the fixture plan once, through the real endpoint."""
    if not _server_up():
        pytest.skip("No server on localhost:8000 for Ablaufplan E2E tests")
    for payload in (_ABLAUFPLAN, _BESCHLUESSE):
        result = _post(payload)
        assert result["ok"], result


@pytest.fixture
def plan_page(page: Page) -> Page:
    # The chat panel is a fixed bottom-right overlay. On the default 720px-tall
    # test viewport it reaches the filter bar's right-hand end, so a click on
    # the view toggle lands on the chat instead. Collapsing it first is what a
    # user working with the chart does; that the panel must not permanently
    # hide content is covered separately, in test_board_and_tree_ui.
    page.add_init_script(
        "try{sessionStorage.setItem("
        "'panel-collapsed-chat-widget-body','true')}catch(e){}"
    )
    page.goto(BASE_URL)
    page.wait_for_selector(".stat-tile", timeout=10000)
    page.click('[data-testid="nav-plan"]')
    page.wait_for_selector(".gantt", timeout=5000)
    # The fixture deliberately uses far-future dates so it cannot collide with
    # real data; the default time window excludes them.
    page.select_option('select[aria-label="Zeitraum"]', "all")
    page.wait_for_timeout(400)
    return page


@pytest.fixture
def decisions_page(page: Page) -> Page:
    page.goto(BASE_URL)
    page.wait_for_selector(".stat-tile", timeout=10000)
    page.click('[data-testid="nav-pendenzen"]')
    page.click('[data-testid="tab-beschluesse"]')
    page.wait_for_selector(".decision-list", timeout=5000)
    return page


# --------------------------------------------------------------------------- #
# Gantt
# --------------------------------------------------------------------------- #


def test_ablaufplan_is_reachable_from_the_sidebar(plan_page: Page):
    assert plan_page.locator(".gantt").is_visible()


def test_activities_render_as_bars_and_milestones_as_diamonds(plan_page: Page):
    """The distinction is the whole reason this is not the Timeline screen."""
    assert plan_page.locator(".gantt-bar").count() > 0
    assert plan_page.locator(".gantt-milestone").count() > 0


def test_a_milestone_never_renders_as_a_bar(plan_page: Page):
    """A point in time has no span, so it must not get a bar element."""
    rows = plan_page.locator(".gantt-row").filter(
        has_text="E2E Konzept-Abnahme"
    )
    assert rows.first.locator(".gantt-milestone").count() == 1
    assert rows.first.locator(".gantt-bar").count() == 0


def test_rows_are_grouped_under_their_phase(plan_page: Page):
    phases = plan_page.locator(".gantt-phase").all_text_contents()
    assert any("E2E Konzept" in p for p in phases)
    assert any("E2E Realisierung" in p for p in phases)


def test_each_status_gets_its_own_bar_class(plan_page: Page):
    """Status has to be encoded on the mark, not only in the tooltip."""
    for cls in ("is-done", "is-running", "is-blocked"):
        assert plan_page.locator(f".gantt-bar.{cls}").count() > 0, cls


def test_a_legend_names_every_status(plan_page: Page):
    """Identity never rests on colour alone — see the dataviz rules."""
    legend = plan_page.locator(".gantt-legend").inner_text()
    for label in ("Laufend", "Offen", "Blockiert", "Erledigt", "Meilenstein", "Heute"):
        assert label in legend, label


def test_progress_fills_part_of_a_running_bar(plan_page: Page):
    # Named rather than `.first`: a running bar whose plan states no progress
    # correctly has no fill, and other fixtures contribute such bars.
    running = plan_page.locator(".gantt-row").filter(
        has_text="E2E Realisierung durchführen"
    ).first.locator(".gantt-bar")
    fill = running.locator(".gantt-progress")
    assert fill.count() == 1
    bar_w = running.bounding_box()["width"]
    fill_w = fill.bounding_box()["width"]
    assert 0 < fill_w < bar_w, f"progress {fill_w} should be inside bar {bar_w}"


def test_bars_sit_in_calendar_order(plan_page: Page):
    """A later activity must start further right — the axis is the encoding."""
    early = plan_page.locator(".gantt-row").filter(
        has_text="E2E Detailkonzept erstellen"
    ).first.locator(".gantt-bar").bounding_box()
    late = plan_page.locator(".gantt-row").filter(
        has_text="E2E Realisierung durchführen"
    ).first.locator(".gantt-bar").bounding_box()
    assert early["x"] < late["x"]


def test_hovering_a_bar_shows_its_dates(plan_page: Page):
    plan_page.locator(".gantt-row").filter(
        has_text="E2E Realisierung durchführen"
    ).first.hover()
    plan_page.wait_for_selector(".gantt-tip", timeout=3000)
    tip = plan_page.locator(".gantt-tip").inner_text()
    assert "21.02.2099" in tip and "30.06.2099" in tip
    assert "45%" in tip


def test_the_table_view_carries_every_encoded_value(plan_page: Page):
    """The chart's accessible equal: nothing is gated behind the bars."""
    plan_page.click('button:has-text("Tabelle")')
    plan_page.wait_for_selector(".data-table", timeout=3000)
    row = plan_page.locator("tbody tr").filter(
        has_text="E2E Realisierung durchführen"
    ).first.inner_text()
    assert "E2E Realisierung" in row      # phase
    assert "21.02.2099" in row            # start
    assert "30.06.2099" in row            # end
    assert "IT" in row                    # owner
    assert "Laufend" in row               # status, as a word
    assert "45" in row                    # progress


def test_phase_filter_narrows_the_chart(plan_page: Page):
    before = plan_page.locator(".gantt-row").count()
    plan_page.select_option('select[aria-label="Phase filtern"]', "E2E Konzept")
    plan_page.wait_for_timeout(400)
    assert plan_page.locator(".gantt-row").count() < before


def test_status_filter_narrows_the_chart(plan_page: Page):
    plan_page.select_option('select[aria-label="Status filtern"]', "blockiert")
    plan_page.wait_for_timeout(400)
    assert plan_page.locator(".gantt-bar.is-blocked").count() > 0
    assert plan_page.locator(".gantt-bar.is-done").count() == 0


def test_the_view_has_exactly_one_hero_figure(plan_page: Page):
    assert plan_page.locator(".hero-value").count() == 1


def test_gantt_raises_no_console_errors(plan_page: Page):
    errors: list[str] = []
    plan_page.on("pageerror", lambda e: errors.append(str(e)))
    plan_page.click('button:has-text("Tabelle")')
    plan_page.wait_for_timeout(400)
    plan_page.click('button:has-text("Balkenplan")')
    plan_page.wait_for_timeout(400)
    assert not errors, errors


# --------------------------------------------------------------------------- #
# Beschlüsse
# --------------------------------------------------------------------------- #


def test_beschluesse_tab_lists_decisions(decisions_page: Page):
    assert decisions_page.locator(".decision-item").count() > 0


def test_a_decision_shows_when_and_by_whom(decisions_page: Page):
    item = decisions_page.locator(".decision-item").filter(
        has_text="E2E Verzicht auf Eigenentwicklung"
    ).first.inner_text()
    assert "15.01.2099" in item
    assert "E2E Steuerungsausschuss" in item
    assert "E2E Checkout" in item


def test_a_decision_shows_its_follow_up_load(decisions_page: Page):
    """One of the two Pendenzen is closed, so it must read 1 of 2."""
    item = decisions_page.locator(".decision-item").filter(
        has_text="E2E Verzicht auf Eigenentwicklung"
    ).first.inner_text()
    assert "1 von 2 Todos offen" in item


def test_decision_status_is_a_labelled_chip(decisions_page: Page):
    """Colour alone never carries the state."""
    chip = decisions_page.locator(".decision-item").filter(
        has_text="E2E Verzicht auf Eigenentwicklung"
    ).first.locator(".chip")
    assert chip.count() == 1
    assert chip.inner_text().strip() == "Beschlossen"
    assert chip.locator(".chip-mark").count() == 1


def test_decisions_do_not_appear_on_the_kanban_board(decisions_page: Page):
    """A Beschluss is a settled fact, not a work package."""
    decisions_page.click('[data-testid="nav-detail"]')
    decisions_page.click('button.tab-btn:has-text("Kanban")')
    decisions_page.wait_for_selector(".kanban-board", timeout=5000)
    assert decisions_page.locator(
        '.kanban-card:has-text("E2E Verzicht auf Eigenentwicklung")'
    ).count() == 0


def test_the_pendenz_termin_is_shown(decisions_page: Page):
    """The Due column read "—" for every row before the importer read dates."""
    decisions_page.click('[data-testid="tab-pendenzen"]')
    decisions_page.fill('[data-testid="pendenzen-search"]', "E2E Vertrag")
    decisions_page.wait_for_timeout(400)
    assert decisions_page.locator('tbody tr:has-text("2099-03-31")').count() > 0


def test_beschluesse_raise_no_console_errors(decisions_page: Page):
    errors: list[str] = []
    decisions_page.on("pageerror", lambda e: errors.append(str(e)))
    decisions_page.click('[data-testid="tab-pendenzen"]')
    decisions_page.wait_for_timeout(300)
    decisions_page.click('[data-testid="tab-beschluesse"]')
    decisions_page.wait_for_timeout(300)
    assert not errors, errors


# --------------------------------------------------------------------------- #
# Cross-source sweep — the altitude and provenance the sweep carries
# --------------------------------------------------------------------------- #

_SWEEP = {
    "schema": "hermes.faelligkeiten/v1",
    "project_ref": "proj/e2e-sweep",
    "project_label": "E2E Sweep",
    "faelligkeiten": [
        {
            "external_ref": "fk/e2e-go-live", "titel": "E2E Go-Live",
            "faellig_am": "2098-11-30", "ebene": "meilenstein",
            "status": "offen", "quelle": "e2e-statusbericht.docx",
        },
        {
            "external_ref": "fk/e2e-bau", "titel": "E2E Bau",
            "start": "2098-07-16", "faellig_am": "2098-10-02",
            "ebene": "arbeitspaket", "status": "laufend",
            "verantwortlich": "IT", "quelle": "e2e-ablaufplan.xlsx",
        },
        {
            "external_ref": "fk/e2e-rechnung", "titel": "E2E Rechnung pruefen",
            "faellig_am": "2098-09-04", "ebene": "aufgabe",
            "status": "offen", "verantwortlich": "Controlling",
            "quelle": "e2e-protokoll.docx",
        },
    ],
}


@pytest.fixture
def sweep_page(page: Page) -> Page:
    _post(_SWEEP)
    page.add_init_script(
        "try{sessionStorage.setItem("
        "'panel-collapsed-chat-widget-body','true')}catch(e){}"
    )
    page.goto(BASE_URL)
    page.wait_for_selector(".stat-tile", timeout=10000)
    page.click('[data-testid="nav-plan"]')
    page.wait_for_selector(".gantt", timeout=5000)
    page.select_option('select[aria-label="Zeitraum"]', "all")
    page.wait_for_timeout(400)
    return page


def test_sweep_draws_all_three_marks(sweep_page: Page):
    """A gate, a span and a dated errand each get their own shape."""
    assert sweep_page.locator(".gantt-milestone").count() > 0
    assert sweep_page.locator(".gantt-bar").count() > 0
    assert sweep_page.locator(".gantt-termin").count() > 0


def test_a_dated_todo_is_a_tick_not_a_diamond(sweep_page: Page):
    row = sweep_page.locator(".gantt-row").filter(has_text="E2E Rechnung pruefen").first
    assert row.locator(".gantt-termin").count() == 1
    assert row.locator(".gantt-milestone").count() == 0
    assert row.locator(".gantt-bar").count() == 0


def test_the_legend_names_the_third_mark(sweep_page: Page):
    assert "Termin ohne Dauer" in sweep_page.locator(".gantt-legend").inner_text()


def test_altitude_can_be_filtered_down_to_the_gates(sweep_page: Page):
    """The reason a lead can live with a list that holds every errand."""
    before = sweep_page.locator(".gantt-row").count()
    sweep_page.select_option('select[aria-label="Ebene filtern"]', "meilenstein")
    sweep_page.wait_for_timeout(400)
    assert sweep_page.locator(".gantt-row").count() < before
    assert sweep_page.locator(".gantt-termin").count() == 0
    assert sweep_page.locator(".gantt-bar").count() == 0


def test_source_filter_appears_once_a_sweep_spans_documents(sweep_page: Page):
    assert sweep_page.locator('select[aria-label="Quelle filtern"]').count() == 1


def test_the_table_shows_altitude_and_source(sweep_page: Page):
    sweep_page.click('button:has-text("Tabelle")')
    sweep_page.wait_for_selector(".data-table", timeout=3000)
    row = sweep_page.locator("tbody tr").filter(
        has_text="E2E Rechnung pruefen"
    ).first.inner_text()
    assert "Aufgaben" in row
    assert "e2e-protokoll.docx" in row


def test_the_time_window_hides_nothing_silently(sweep_page: Page):
    """One far-future date used to crush the axis with no way back."""
    sweep_page.select_option('select[aria-label="Zeitraum"]', "12")
    sweep_page.wait_for_timeout(400)
    notice = sweep_page.locator(".notice-info")
    assert notice.count() == 1
    assert "ausserhalb" in notice.inner_text()

    # And the way back is one click.
    sweep_page.click('button:has-text("Ganzen Zeitraum zeigen")')
    sweep_page.wait_for_timeout(400)
    assert sweep_page.locator(".notice-info").count() == 0


# --------------------------------------------------------------------------- #
# Person filter, inline owner editing, and zoom
# --------------------------------------------------------------------------- #


def test_owner_filter_lists_everyone_who_owns_something(sweep_page: Page):
    opts = sweep_page.locator('[data-testid="filter-owner"] option').all_text_contents()
    assert any(o.strip() == "IT" for o in opts)
    assert any(o.strip() == "Controlling" for o in opts)
    # Unassigned work is a finding, so it gets its own entry rather than being
    # invisible behind "all".
    assert any("ohne Verantwortlichen" in o for o in opts)


def test_owner_filter_narrows_to_one_person(sweep_page: Page):
    before = sweep_page.locator(".gantt-row").count()
    sweep_page.select_option('[data-testid="filter-owner"]', "Controlling")
    sweep_page.wait_for_timeout(400)
    after = sweep_page.locator(".gantt-row").count()
    assert 0 < after < before
    owners = sweep_page.locator(".gantt-row-owner").all_text_contents()
    assert {o.strip() for o in owners} == {"Controlling"}


def test_owner_filter_can_find_unassigned_work(sweep_page: Page):
    sweep_page.select_option('[data-testid="filter-owner"]', "__ohne__")
    sweep_page.wait_for_timeout(400)
    rows = sweep_page.locator(".gantt-row").all_text_contents()
    assert any("E2E Go-Live" in r for r in rows)   # the fixture row with no owner
    assert not any("Controlling" in r for r in rows)


def _table(page: Page) -> None:
    page.click('button:has-text("Tabelle")')
    page.wait_for_selector(".data-table", timeout=3000)


def test_owner_is_editable_and_persists(sweep_page: Page):
    """The write has to reach disk, not just the rendered table."""
    _table(sweep_page)
    row = sweep_page.locator("tbody tr").filter(has_text="E2E Rechnung pruefen").first
    assert row.locator(".owner-button").inner_text().strip() == "Controlling"
    row.locator(".owner-button").click()
    sweep_page.locator(".owner-input").fill("E2E Frau Meier")
    sweep_page.keyboard.press("Enter")
    sweep_page.wait_for_timeout(2200)

    row = sweep_page.locator("tbody tr").filter(has_text="E2E Rechnung pruefen").first
    assert row.locator(".owner-button").inner_text().strip() == "E2E Frau Meier"

    # A reload proves it was written, not just re-rendered.
    sweep_page.goto(BASE_URL)
    sweep_page.wait_for_selector(".stat-tile", timeout=10000)
    sweep_page.click('[data-testid="nav-plan"]')
    sweep_page.wait_for_selector(".gantt", timeout=5000)
    sweep_page.select_option('select[aria-label="Zeitraum"]', "all")
    _table(sweep_page)
    row = sweep_page.locator("tbody tr").filter(has_text="E2E Rechnung pruefen").first
    assert row.locator(".owner-button").inner_text().strip() == "E2E Frau Meier"

    # Restore, so the fixture is stable for the next run.
    row.locator(".owner-button").click()
    sweep_page.locator(".owner-input").fill("Controlling")
    sweep_page.keyboard.press("Enter")
    sweep_page.wait_for_timeout(2000)


def test_an_unassigned_row_invites_assignment(sweep_page: Page):
    _table(sweep_page)
    row = sweep_page.locator("tbody tr").filter(has_text="E2E Go-Live").first
    assert "zuweisen" in row.locator(".owner-button").inner_text()


def test_escape_abandons_an_owner_edit(sweep_page: Page):
    _table(sweep_page)
    row = sweep_page.locator("tbody tr").filter(has_text="E2E Bau").first
    before = row.locator(".owner-button").inner_text().strip()
    row.locator(".owner-button").click()
    sweep_page.locator(".owner-input").fill("Verworfen")
    sweep_page.keyboard.press("Escape")
    sweep_page.wait_for_timeout(1200)
    row = sweep_page.locator("tbody tr").filter(has_text="E2E Bau").first
    assert row.locator(".owner-button").inner_text().strip() == before


def test_zoom_widens_the_track_without_hiding_rows(sweep_page: Page):
    """Zoom is a different lever from the time window: same rows, more room."""
    rows_before = sweep_page.locator(".gantt-row").count()
    width_before = sweep_page.locator(".gantt").bounding_box()["width"]
    sweep_page.click('[data-testid="zoom-in"]')
    sweep_page.wait_for_timeout(400)
    assert sweep_page.locator(".gantt").bounding_box()["width"] > width_before
    assert sweep_page.locator(".gantt-row").count() == rows_before


def test_zoom_out_returns_to_the_fitted_width(sweep_page: Page):
    width_before = sweep_page.locator(".gantt").bounding_box()["width"]
    sweep_page.click('[data-testid="zoom-in"]')
    sweep_page.wait_for_timeout(300)
    sweep_page.click('[data-testid="zoom-out"]')
    sweep_page.wait_for_timeout(300)
    assert sweep_page.locator(".gantt").bounding_box()["width"] == pytest.approx(
        width_before, rel=0.02
    )


def test_zoom_is_bounded_at_both_ends(sweep_page: Page):
    assert sweep_page.locator('[data-testid="zoom-out"]').is_disabled()
    for _ in range(8):
        if sweep_page.locator('[data-testid="zoom-in"]').is_disabled():
            break
        sweep_page.locator('[data-testid="zoom-in"]').click()
        sweep_page.wait_for_timeout(150)
    assert sweep_page.locator('[data-testid="zoom-in"]').is_disabled()
    assert sweep_page.locator('[data-testid="zoom-level"]').inner_text() == "600%"


def test_zoom_control_is_absent_in_the_table_view(sweep_page: Page):
    """It scales a time axis; a table has none."""
    _table(sweep_page)
    assert sweep_page.locator('[data-testid="zoom-in"]').count() == 0


# --------------------------------------------------------------------------- #
# What the cleanup removed
# --------------------------------------------------------------------------- #


def test_the_detail_screen_no_longer_carries_a_timeline_tab(page: Page):
    """It plotted the same schedule.json this screen shows in full, and its
    status was derived from the date rather than stated by the plan."""
    page.goto(BASE_URL)
    page.wait_for_selector(".stat-tile", timeout=10000)
    page.click('[data-testid="nav-detail"]')
    page.wait_for_timeout(600)
    labels = [t.strip() for t in page.locator(".tab-bar .tab-btn").all_text_contents()]
    assert not any(t.startswith("Timeline") for t in labels), labels
    assert any(t.startswith("Kanban") for t in labels)


def test_the_picker_no_longer_offers_the_subsumed_exports(page: Page):
    page.goto(BASE_URL)
    page.wait_for_selector(".stat-tile", timeout=10000)
    page.click("button:has-text('Import JSON')")
    page.wait_for_selector('[data-testid="prompt-kind-faelligkeiten"]', timeout=5000)
    assert page.locator('[data-testid="prompt-kind-ablaufplan"]').count() == 0
    assert page.locator('[data-testid="prompt-kind-timeline"]').count() == 0
