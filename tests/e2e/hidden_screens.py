"""What the sidebar currently offers, asked of the app rather than written down.

Two screens ship hidden — Timeline & WBS and Risks — through
``HIDDEN_SCREENS`` in ``webapp/static/app.js``. That is deliberately a hide,
not a delete: the components, the routes, the endpoints behind them and their
tests all stay exactly where they are, so bringing a screen back is emptying
that one list.

Which only holds if the tests come back with it. A hand-written
``pytest.skip`` on each affected test would make the return a hunt through the
suite; these helpers ask the running page which screens exist, so the skips
clear themselves on the next run after the list is emptied.

A skipped test is not a passing test, and nothing here pretends otherwise.
What it buys is that the skip reason names the switch that caused it, instead
of a timeout on a selector that will never appear.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page


def visible_screens(page: Page) -> list[str] | None:
    """The screen keys the sidebar offers, or ``None`` if the build predates
    the list — in which case no screen is hidden and nothing should skip."""
    return page.evaluate("() => window.HERMES_VISIBLE_SCREENS ?? null")


def require_screen(page: Page, key: str) -> None:
    """Skip the calling test unless ``key`` is reachable from the sidebar.

    Call it on a page that has already loaded: the answer lives on ``window``,
    published by ``app.js``.
    """
    visible = visible_screens(page)
    if visible is not None and key not in visible:
        pytest.skip(
            f"The {key!r} screen is hidden from the sidebar — see "
            f"HIDDEN_SCREENS in webapp/static/app.js. Offered: {visible}"
        )


def stored_risks(page: Page, base_url: str) -> list[dict]:
    """The risk register, read from the API the page itself uses.

    The count used to be readable off the Risks nav badge, and the register
    off the Risks screen. Hiding the screen took both, so a test about
    *importing* risks has no rendered number left to compare.

    Asking ``/api/dashboard`` keeps those tests testing what they are named
    for — an import lands; re-importing the same id does not duplicate — which
    is a property of the pipeline, not of a badge. The fetch goes through the
    page so it carries the same origin the dashboard's own requests do.
    """
    return page.evaluate(
        """async (url) => {
            const res = await fetch(url + '/api/dashboard', {cache: 'no-store'});
            if (!res.ok) throw new Error('dashboard ' + res.status);
            const data = await res.json();
            return data.risks || [];
        }""",
        base_url,
    )


def risk_count(page: Page, base_url: str) -> int:
    """How many risks are stored. See :func:`stored_risks`."""
    return len(stored_risks(page, base_url))


def risk_titles(page: Page, base_url: str) -> list[str]:
    """The titles in the register. See :func:`stored_risks`."""
    return [r.get("title", "") for r in stored_risks(page, base_url)]
