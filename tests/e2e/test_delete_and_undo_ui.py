"""E2E browser tests for deleting to-dos and projects, and for Undo.

Nothing on the dashboard could be removed before this: the stores grew but
never shrank, so a typo or a duplicate import was permanent. The point of these
tests is less "does the button call the endpoint" than the two things that make
a destructive action safe to ship — the confirm actually gates it, and the Undo
actually brings the row back.

Requires Playwright and a live server on http://localhost:8000; the module
skips cleanly when either is missing.
"""

from __future__ import annotations

import socket
import uuid

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
def todo_page(page: Page) -> Page:
    """The Todo screen with one to-do this test created and owns.

    Each test makes its own row rather than deleting whatever happens to be
    first: these tests really delete things, and a shared fixture row would let
    one test's delete decide another test's starting state.
    """
    page.add_init_script(
        "try{sessionStorage.setItem("
        "'panel-collapsed-chat-widget-body','true')}catch(e){}"
    )
    page.goto(BASE_URL)
    page.wait_for_selector(".nav-btn", timeout=10000)
    return page


def _unique(prefix: str) -> str:
    """A title no other run can collide with.

    These tests run against the developer's real database, which keeps every
    row an earlier run created. With a fixed title, a delete would leave the
    identically-named rows from previous runs behind and the assertion would
    fail — and only in a full-suite run, never in isolation.
    """
    return f"{prefix} {uuid.uuid4().hex[:8]}"


def _make_todo(page: Page, title: str) -> None:
    """Create a to-do through the API the page is already talking to."""
    page.evaluate(
        """async (t) => {
            const r = await fetch('/api/todos', {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({title: t}),
            });
            if (!r.ok) throw new Error('create failed: ' + r.status);
        }""",
        title,
    )
    page.reload()
    page.wait_for_selector(".nav-btn", timeout=10000)


def _open_todos(page: Page) -> None:
    page.get_by_role("button", name="Planung").first.click()
    # Planung opens on the timeline; these tests all work the list.
    page.wait_for_selector('[data-testid="lens-liste"]', timeout=10000)
    page.locator('[data-testid="lens-liste"]').click()
    page.wait_for_selector('[data-testid="work-search"]', timeout=10000)


def _row(page: Page, title: str):
    return page.locator("tr", has_text=title).first


# --------------------------------------------------------------------------- #
# Deleting a to-do
# --------------------------------------------------------------------------- #


def test_a_todo_row_offers_a_delete_button(todo_page: Page) -> None:
    title = _unique("E2E todo")
    _make_todo(todo_page, title)
    _open_todos(todo_page)
    todo_page.locator('[data-testid="work-search"]').fill(title)
    expect(_row(todo_page, title).locator(
        '[data-testid="delete-work"]'
    )).to_have_count(1)


def test_cancelling_the_confirm_keeps_the_todo(todo_page: Page) -> None:
    """The guard has to actually guard, or the confirm is theatre."""
    title = _unique("E2E todo")
    _make_todo(todo_page, title)
    _open_todos(todo_page)
    todo_page.locator('[data-testid="work-search"]').fill(title)

    todo_page.on("dialog", lambda d: d.dismiss())
    _row(todo_page, title).locator('[data-testid="delete-work"]').click()
    todo_page.wait_for_timeout(500)

    expect(_row(todo_page, title)).to_have_count(1)


def test_confirming_removes_the_todo_from_the_table(todo_page: Page) -> None:
    title = _unique("E2E todo")
    _make_todo(todo_page, title)
    _open_todos(todo_page)
    todo_page.locator('[data-testid="work-search"]').fill(title)

    todo_page.on("dialog", lambda d: d.accept())
    _row(todo_page, title).locator('[data-testid="delete-work"]').click()

    expect(todo_page.locator("tr", has_text=title)).to_have_count(0, timeout=10000)


def test_deleting_shows_an_undo_button(todo_page: Page) -> None:
    title = _unique("E2E todo")
    _make_todo(todo_page, title)
    _open_todos(todo_page)
    todo_page.locator('[data-testid="work-search"]').fill(title)

    todo_page.on("dialog", lambda d: d.accept())
    _row(todo_page, title).locator(
        '[data-testid="delete-work"]'
    ).click()

    expect(todo_page.locator('[data-testid="toast-undo"]')).to_be_visible(
        timeout=10000
    )


def test_undo_brings_the_todo_back(todo_page: Page) -> None:
    """The whole reason delete is soft — an Undo that cannot restore is a lie."""
    title = _unique("E2E todo")
    _make_todo(todo_page, title)
    _open_todos(todo_page)
    todo_page.locator('[data-testid="work-search"]').fill(title)

    todo_page.on("dialog", lambda d: d.accept())
    _row(todo_page, title).locator('[data-testid="delete-work"]').click()
    expect(todo_page.locator("tr", has_text=title)).to_have_count(
        0, timeout=10000
    )

    todo_page.locator('[data-testid="toast-undo"]').click()

    _open_todos(todo_page)
    todo_page.locator('[data-testid="work-search"]').fill(title)
    expect(_row(todo_page, title)).to_have_count(1, timeout=10000)


def test_the_undo_button_disappears_once_used(todo_page: Page) -> None:
    """A second click would restore twice and only confuse."""
    title = _unique("E2E todo")
    _make_todo(todo_page, title)
    _open_todos(todo_page)
    todo_page.locator('[data-testid="work-search"]').fill(title)

    todo_page.on("dialog", lambda d: d.accept())
    _row(todo_page, title).locator('[data-testid="delete-work"]').click()
    todo_page.locator('[data-testid="toast-undo"]').click()

    expect(todo_page.locator('[data-testid="toast-undo"]')).to_have_count(
        0, timeout=10000
    )


def test_deleting_raises_no_console_errors(todo_page: Page) -> None:
    errors: list[str] = []
    todo_page.on(
        "console", lambda m: errors.append(m.text) if m.type == "error" else None
    )
    todo_page.on("pageerror", lambda e: errors.append(str(e)))

    title = _unique("E2E todo")
    _make_todo(todo_page, title)
    _open_todos(todo_page)
    todo_page.locator('[data-testid="work-search"]').fill(title)
    todo_page.on("dialog", lambda d: d.accept())
    _row(todo_page, title).locator('[data-testid="delete-work"]').click()
    expect(todo_page.locator('[data-testid="toast-undo"]')).to_be_visible(
        timeout=10000
    )

    assert errors == []


# --------------------------------------------------------------------------- #
# Deleting a project
# --------------------------------------------------------------------------- #


def _make_project(page: Page, pid: str) -> None:
    page.evaluate(
        """async (p) => {
            const r = await fetch('/api/projects', {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({project_id: p}),
            });
            if (!r.ok && r.status !== 409) throw new Error('create failed');
        }""",
        pid,
    )
    page.reload()
    page.wait_for_selector(".nav-btn", timeout=10000)


def _open_projects(page: Page) -> None:
    page.get_by_role("button", name="Projects").first.click()
    page.wait_for_selector('input[aria-label="Filter projects"]', timeout=10000)


def test_a_project_row_offers_a_delete_button(todo_page: Page) -> None:
    pid = _unique("e2e-proj").replace(" ", "-")
    _make_project(todo_page, pid)
    _open_projects(todo_page)
    todo_page.locator('input[aria-label="Filter projects"]').fill(pid)
    expect(_row(todo_page, pid).locator(
        '[data-testid="delete-project"]'
    )).to_have_count(1)


def test_deleting_a_project_does_not_also_open_it(todo_page: Page) -> None:
    """The row navigates on click; the delete button must stop propagation."""
    pid = _unique("e2e-proj").replace(" ", "-")
    _make_project(todo_page, pid)
    _open_projects(todo_page)
    todo_page.locator('input[aria-label="Filter projects"]').fill(pid)

    todo_page.on("dialog", lambda d: d.dismiss())
    _row(todo_page, pid).locator(
        '[data-testid="delete-project"]'
    ).click()
    todo_page.wait_for_timeout(500)

    # Still on the project list, not pushed into the detail screen.
    expect(todo_page.locator('input[aria-label="Filter projects"]')).to_be_visible()


def test_undo_brings_the_project_back(todo_page: Page) -> None:
    pid = _unique("e2e-proj").replace(" ", "-")
    _make_project(todo_page, pid)
    _open_projects(todo_page)
    todo_page.locator('input[aria-label="Filter projects"]').fill(pid)

    todo_page.on("dialog", lambda d: d.accept())
    _row(todo_page, pid).locator(
        '[data-testid="delete-project"]'
    ).click()
    expect(todo_page.locator('[data-testid="toast-undo"]')).to_be_visible(
        timeout=10000
    )
    todo_page.locator('[data-testid="toast-undo"]').click()

    _open_projects(todo_page)
    todo_page.locator('input[aria-label="Filter projects"]').fill(pid)
    expect(_row(todo_page, pid)).to_have_count(1, timeout=10000)
