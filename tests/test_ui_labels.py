"""The user-visible name for a Pendenz is "Todo" on every surface.

The rename from "Pendenzen" to "Todo" is deliberately cosmetic: the ``pendenz``
node kind, the ``pendenzen`` import schema, the ``pd/`` external-ref prefix, the
``pendenz-add`` CLI command and every JSON key keep their original names, so
existing exports and scripts keep working. Only what a person reads changes.

That split is exactly what makes the rename easy to half-apply. It first landed
on the Vue dashboard alone and missed the static HTML dashboard, whose ``<nav>``
still read "Pendenzen" — a second renderer nobody thought to grep. These tests
pin the visible label on all four surfaces at once, so the next person to touch
one of them cannot leave the others behind.

Identifiers are checked too, in the opposite direction: they must NOT be
renamed, so a well-meaning find-and-replace over the whole tree fails here
instead of silently breaking every previously exported JSON file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_assistant.dashboard_html import DashboardData, render_html

_STATIC = Path(__file__).resolve().parents[1] / "src/hermes_assistant/webapp/static"


# --------------------------------------------------------------------------- #
# The static HTML dashboard — the surface the first rename pass missed
# --------------------------------------------------------------------------- #

@pytest.fixture
def rendered() -> str:
    """A dashboard rendered from empty data — labels do not depend on content."""
    return render_html(DashboardData(generated_at="2026-09-02T00:00:00Z"))


def test_html_dashboard_nav_says_todo(rendered: str) -> None:
    assert ">Todo</a>" in rendered


def test_html_dashboard_section_heading_says_todo(rendered: str) -> None:
    assert "<h2>Todo</h2>" in rendered


def test_html_dashboard_shows_no_pendenzen_label(rendered: str) -> None:
    """No visible "Pendenzen" text anywhere in the page.

    The anchor keeps ``id="pendenzen"``/``href="#pendenzen"`` on purpose — a
    fragment id is a URL, and existing bookmarks and deep links should survive a
    label change. So assert on the rendered *text*, not on the substring.
    """
    import re

    text = re.sub(r"<[^>]+>", " ", rendered)
    assert "Pendenz" not in text


def test_html_dashboard_keeps_the_pendenzen_anchor(rendered: str) -> None:
    """The deep link must keep working; only the label changed."""
    assert 'href="#pendenzen"' in rendered
    assert 'id="pendenzen"' in rendered


# --------------------------------------------------------------------------- #
# The TUI
# --------------------------------------------------------------------------- #

def test_tui_footer_binding_says_todo() -> None:
    from hermes_assistant.tui.app import HermesApp

    labels = {b[2] for b in HermesApp.BINDINGS}
    assert "Todo" in labels
    assert "Pendenzen" not in labels


def test_tui_binding_action_keeps_its_name() -> None:
    """The action is code, not copy — renaming it would break the key binding."""
    from hermes_assistant.tui.app import HermesApp

    actions = {b[1] for b in HermesApp.BINDINGS}
    assert "goto_pendenzen" in actions


# --------------------------------------------------------------------------- #
# The Vue dashboard
# --------------------------------------------------------------------------- #

def test_the_vue_sidebar_no_longer_says_pendenzen() -> None:
    """The sidebar entry is now "Planung" — the merged screen, renamed.

    This used to assert ``label: 'Todo'``, which after the merge still matched
    — but on the create dialog's entry, not the sidebar's. A test that passes
    by matching something other than what its name claims is worse than no
    test, so it asserts the absence of the old word instead, which is what
    was actually being protected.
    """
    source = (_STATIC / "app.js").read_text(encoding="utf-8")
    assert "label: 'Pendenzen'" not in source
    assert "label: 'Planung'" in source


def test_chat_placeholder_says_todos() -> None:
    source = (_STATIC / "chat.js").read_text(encoding="utf-8")
    assert "risks, todos or the plan" in source


# --------------------------------------------------------------------------- #
# The identifiers that must survive the rename
# --------------------------------------------------------------------------- #

def test_the_node_kind_is_still_pendenz() -> None:
    """Renaming this would orphan every Pendenz already in a user's store."""
    from hermes_assistant.tasks.pendenzen import Pendenz

    assert Pendenz.model_fields["node_kind"].default == "pendenz"


def test_the_cli_command_is_still_pendenz_add() -> None:
    """A renamed command breaks anyone's scripts; the help text is free to change."""
    from hermes_assistant.cli import app

    names = {c.name for c in app.registered_commands}
    assert "pendenz-add" in names
