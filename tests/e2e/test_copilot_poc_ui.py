"""E2E browser tests for the temporary Copilot POC screen.

The page exists so that evaluating the integration does not mean reading
source. That makes its contract unusual: it is mostly prose, and prose can rot
silently. What is worth pinning is the part that is not prose — the live
checklist, the probe, and the promise that opening the page contacts nobody.

Requires Playwright and a live server on http://localhost:8000; the module
skips cleanly when either is missing.
"""

from __future__ import annotations

import json
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
def poc_page(page: Page) -> Page:
    page.add_init_script(
        "try{sessionStorage.setItem("
        "'panel-collapsed-chat-widget-body','true')}catch(e){}"
    )
    page.goto(BASE_URL)
    page.wait_for_selector(".nav-btn", timeout=15000)
    page.evaluate("try{localStorage.removeItem('hermes-nav-order')}catch(e){}")
    page.reload()
    page.wait_for_selector(".nav-btn", timeout=15000)
    page.click('[data-testid="nav-copilot"]')
    page.wait_for_selector('[data-testid="poc-checks"]', timeout=15000)
    return page


_READY = {
    "ready": True,
    "checks": [
        {"id": i, "label": i, "ok": True, "detail": "ok", "fix": "—"}
        for i in ("enabled", "tenant", "client", "msal", "token")
    ],
    "limits": {"max_query_chars": 1500, "max_results": 25,
               "data_sources": ["sharePoint"]},
    "scopes": {"retrieval": ["Files.Read.All"], "chat": ["Mail.Read"]},
    "prompts": [],
}


def _route_status(page: Page, body: dict) -> None:
    page.route(
        "**/api/m365/status",
        lambda r: r.fulfill(status=200, content_type="application/json",
                            body=json.dumps(body)),
    )


# --------------------------------------------------------------------------- #
# The sidebar
# --------------------------------------------------------------------------- #


def test_the_sidebar_offers_the_page(poc_page: Page) -> None:
    labels = [
        t.strip().split("\n")[0]
        for t in poc_page.locator(".nav-btn span:nth-child(2)").all_text_contents()
    ]
    assert "Copilot POC" in labels


def test_the_entry_is_marked_temporary(poc_page: Page) -> None:
    """A page meant to be deleted should say so where it is clicked, not only
    once it is open."""
    marker = poc_page.locator('[data-testid="nav-temp-marker"]')
    expect(marker).to_have_count(1)
    assert marker.inner_text().strip().lower() == "temp"


def test_the_page_carries_no_count_badge(poc_page: Page) -> None:
    """There is nothing to count, and a "0" beside a documentation page reads
    as "nothing here" rather than "not a list"."""
    assert poc_page.locator('[data-testid="nav-copilot"] .nav-count').count() == 0


def test_the_new_screen_did_not_displace_the_others(poc_page: Page) -> None:
    labels = [
        t.strip().split("\n")[0]
        for t in poc_page.locator(".nav-btn span:nth-child(2)").all_text_contents()
    ]
    assert labels[:6] == [
        "Overview", "Projects", "Timeline & WBS", "Planung", "Risks", "Reviews"
    ]


def test_a_stored_order_from_before_still_gets_the_new_entry(page: Page) -> None:
    """Somebody who arranged their sidebar last week must not be the one
    person who cannot reach the new page."""
    page.goto(BASE_URL)
    page.wait_for_selector(".nav-btn", timeout=15000)
    page.evaluate(
        """() => localStorage.setItem('hermes-nav-order', JSON.stringify(
            ['risks', 'overview', 'projects', 'detail', 'work', 'reviews']))"""
    )
    page.reload()
    page.wait_for_selector(".nav-btn", timeout=15000)
    labels = [
        t.strip().split("\n")[0]
        for t in page.locator(".nav-btn span:nth-child(2)").all_text_contents()
    ]
    assert labels[0] == "Risks"          # the stored order is honoured
    assert "Copilot POC" in labels       # and the new screen still arrives


# --------------------------------------------------------------------------- #
# The page
# --------------------------------------------------------------------------- #


def test_the_page_says_it_is_temporary(poc_page: Page) -> None:
    assert "temporär" in poc_page.locator(".page-sub").inner_text().lower()


def test_both_interfaces_are_documented(poc_page: Page) -> None:
    """Conflating the two is the main source of confusion: one works today
    with no setup, the other needs an app registration and is off."""
    text = poc_page.locator(".poc-card").all_inner_texts()
    assert any("Prompt-Export" in t for t in text)
    assert any("Graph API" in t for t in text)


def test_the_checklist_names_every_precondition(poc_page: Page) -> None:
    rows = poc_page.locator('[data-testid="poc-checks"] tbody tr')
    assert rows.count() == 5
    ids = [rows.nth(i).get_attribute("data-check") for i in range(rows.count())]
    assert set(ids) == {"enabled", "tenant", "client", "msal", "token"}


def test_a_failing_row_shows_the_remedy(poc_page: Page) -> None:
    failing = poc_page.locator('[data-testid="poc-checks"] tbody tr').filter(
        has=poc_page.locator(".poc-mark.is-bad")
    )
    if not failing.count():
        pytest.skip("this machine has the integration fully configured")
    assert failing.first.locator("code").count() == 1


def test_the_state_of_a_row_is_not_colour_alone(poc_page: Page) -> None:
    marks = poc_page.locator(".poc-mark")
    assert marks.count() == 5
    for i in range(marks.count()):
        assert marks.nth(i).inner_text().strip() in {"✓", "✗"}


def test_the_setup_steps_are_ordered(poc_page: Page) -> None:
    """The order IS the instruction: consent before sign-in, sign-in before
    the probe."""
    steps = poc_page.locator('[data-testid="poc-steps"] li')
    assert steps.count() >= 6
    assert steps.first.evaluate("e => e.closest('ol') !== null")


def test_the_prompts_are_listed_and_reachable(poc_page: Page) -> None:
    rows = poc_page.locator('[data-testid="poc-prompts"] tbody tr')
    assert rows.count() == 6
    href = rows.first.locator("a").get_attribute("href")
    resp = poc_page.request.get(BASE_URL + href)
    assert resp.status == 200
    assert len(resp.text()) > 100


def test_the_test_suites_are_named(poc_page: Page) -> None:
    text = poc_page.locator('[data-testid="poc-tests"]').inner_text()
    for suite in (
        "test_m365_copilot.py",
        "test_copilot_tool_prompts.py",
        "test_copilot_adapter.py",
        "test_no_cloud.py",
    ):
        assert suite in text


# --------------------------------------------------------------------------- #
# The probe
# --------------------------------------------------------------------------- #


def test_opening_the_page_does_not_run_the_probe(poc_page: Page) -> None:
    """The probe makes a real call to Microsoft. Doing that because somebody
    opened a documentation page would be a surprise with a bill attached."""
    seen: list[str] = []
    poc_page.on(
        "request",
        lambda r: seen.append(r.url) if "/api/m365/probe" in r.url else None,
    )
    poc_page.click('[data-testid="nav-overview"]')
    poc_page.wait_for_timeout(400)
    poc_page.click('[data-testid="nav-copilot"]')
    poc_page.wait_for_selector('[data-testid="poc-checks"]', timeout=10000)
    poc_page.wait_for_timeout(600)
    assert seen == []


def test_the_probe_reports_a_missing_setup_rather_than_failing(poc_page: Page) -> None:
    poc_page.click('[data-testid="poc-probe"]')
    result = poc_page.locator('[data-testid="poc-probe-result"]')
    expect(result).to_be_visible(timeout=15000)
    assert result.inner_text().strip()


def test_a_successful_probe_is_shown_as_a_success(page: Page) -> None:
    page.route(
        "**/api/m365/probe",
        lambda r: r.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"ok": True, "stage": "retrieval", "hits": 3,
                             "extracts": 9, "titles": ["Projektstatus.docx"]}),
        ),
    )
    _route_status(page, _READY)
    page.goto(f"{BASE_URL}/#/copilot")
    page.wait_for_selector('[data-testid="poc-probe"]', timeout=15000)
    page.click('[data-testid="poc-probe"]')
    result = page.locator('[data-testid="poc-probe-result"]')
    expect(result).to_contain_text("3 Dokumente", timeout=10000)
    assert "Projektstatus.docx" in result.inner_text()


def test_the_verdict_flips_when_everything_is_configured(page: Page) -> None:
    _route_status(page, _READY)
    page.goto(f"{BASE_URL}/#/copilot")
    page.wait_for_selector('[data-testid="poc-verdict"]', timeout=15000)
    assert "Eingerichtet" in page.locator('[data-testid="poc-verdict"]').inner_text()
    assert page.locator(".poc-mark.is-bad").count() == 0


def test_the_page_raises_no_console_errors(poc_page: Page) -> None:
    errors: list[str] = []
    poc_page.on("pageerror", lambda e: errors.append(str(e)))
    poc_page.click('[data-testid="poc-refresh"]')
    poc_page.wait_for_timeout(1200)
    assert not errors, errors
