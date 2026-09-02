"""HermesApp: main TUI application (requires textual at runtime).

``HermesApp`` is defined at module level so tests can import it directly::

    from hermes_assistant.tui.app import HermesApp

Testing seams
-------------
_disable_auto_refresh (bool, default False)
    Set to ``True`` before calling ``run_test()`` to skip the
    ``set_interval()`` auto-refresh timer.  Refreshes can then be driven
    explicitly via ``action_refresh()`` or ``pilot.press("r")``.

_injected_now (datetime | None, default None)
    Set to a UTC ``datetime`` before calling ``_do_refresh()`` /
    ``pilot.press("r")`` to simulate a virtual clock.  When ``None`` (the
    production default) the real UTC timestamp is used for timeline-status
    derivation.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime

from hermes_assistant.dashboard_html import DashboardData
from hermes_assistant.tui.models import validate_safe_view
from hermes_assistant.tui.refresh import compute_fingerprint, diff_sections, load_fresh
from hermes_assistant.tui.screens import (
    make_help_modal,
    make_pendenzen_screen,
    make_project_list_screen,
    make_reviews_screen,
)

_TEXTUAL_INSTALLED = importlib.util.find_spec("textual") is not None

# Conditionally import textual.  The mypy override ``ignore_missing_imports = true``
# for textual.* already suppresses missing-import errors, so no ``# type: ignore``
# comments are needed here; they would just become "unused-ignore" warnings.
if _TEXTUAL_INSTALLED:
    from textual.app import App
    from textual.containers import Container
    from textual.reactive import reactive
    from textual.widgets import Footer, Header, Label
else:
    App = object  # noqa
    reactive = lambda val: val  # noqa: E731

_refresh_interval = 5.0  # seconds


def _require_textual() -> None:
    """Raise ImportError with install hint if textual is not available."""
    if not _TEXTUAL_INSTALLED:
        raise ImportError(
            'TUI requires textual. Install with: pip install "hermes-assistant[tui]"'
        )


class HermesApp(App):  # noqa
    """Interactive HERMES dashboard (read-only).

    Testing seams (set these before ``run()`` / ``run_test()``)::

        app = HermesApp()
        app._disable_auto_refresh = True   # Seam 3: no auto-timer
        app._injected_now = datetime(2026, 8, 7, tzinfo=UTC)  # Seam 2: virtual clock
    """

    CSS = """\
Screen { background: $surface; }
#status-bar {
    dock: bottom; height: 1;
    background: $panel; color: $text-muted;
    padding: 0 1;
}
#main { height: 1fr; }
"""

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("1", "goto_projects", "Projects"),
        ("3", "goto_pendenzen", "Todo"),
        ("4", "goto_reviews", "Reviews"),
        ("r", "refresh", "Refresh"),
        ("d", "toggle_dark", "Theme"),
        ("question_mark", "help", "Help"),
    ]

    dark = reactive(True)

    # -- Testing seams ------------------------------------------------------ #
    _disable_auto_refresh: bool = False   # Seam 3: disable set_interval()
    _injected_now: datetime | None = None  # Seam 2: virtual clock for status derivation

    def __init__(self) -> None:
        _require_textual()
        super().__init__()
        self._data: DashboardData | None = None
        self._fingerprint: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def compose(self):  # noqa
        yield Header(show_clock=True)
        yield Container(id="main")
        yield Label("Loading…", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self._do_refresh()
        # Seam 3: skip auto-refresh when disabled (e.g. in tests)
        if not self._disable_auto_refresh:
            self.set_interval(_refresh_interval, self._auto_refresh)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _do_refresh(self, *, force: bool = False) -> None:
        """Load or reload dashboard data; update the active screen.

        Args:
            force: Skip fingerprint comparison and always reload.

        The virtual clock (Seam 2) is read from ``self._injected_now``:
        when not None it is forwarded to ``load_fresh()`` so that timeline
        item statuses are computed relative to that timestamp rather than
        the real wall clock.
        """
        new_fp = compute_fingerprint()
        if not force and new_fp == self._fingerprint and self._data is not None:
            self._set_status("No changes detected.")
            return
        try:
            # Seam 2: pass injected timestamp for virtual-clock testing
            new_data = load_fresh(now=self._injected_now)
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"[red]Error loading data: {exc}[/red]")
            return

        violations = validate_safe_view(new_data)
        if violations:
            self._set_status(f"[red]Confidentiality: {violations[0]}[/red]")
            return

        if self._data is not None:
            changed = diff_sections(self._data, new_data)
            status_msg = f"Refreshed. Changed: {', '.join(sorted(changed)) or 'none'}"
        else:
            status_msg = f"Loaded {len(new_data.projects)} project(s)."

        self._data = new_data
        self._fingerprint = new_fp
        self._set_status(status_msg)

        # Push the projects screen on first load
        if len(self.screen_stack) <= 1:
            self.push_screen(make_project_list_screen(self._data))

    def _auto_refresh(self) -> None:
        self._do_refresh()

    def _set_status(self, msg: str) -> None:
        try:
            self.query_one("#status-bar", Label).update(msg)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_goto_projects(self) -> None:
        if self._data is None:
            return
        # Pop back to root then push fresh projects screen
        while len(self.screen_stack) > 1:
            self.pop_screen()
        self.push_screen(make_project_list_screen(self._data))

    def action_goto_pendenzen(self) -> None:
        if self._data is None:
            return
        self.push_screen(make_pendenzen_screen(self._data))

    def action_goto_reviews(self) -> None:
        if self._data is None:
            return
        self.push_screen(make_reviews_screen(self._data))

    def action_refresh(self) -> None:
        self._do_refresh(force=True)

    def action_toggle_dark(self) -> None:
        self.dark = not self.dark

    def action_help(self) -> None:
        self.push_screen(make_help_modal())


# ---------------------------------------------------------------------------
# Module-level entry points (backward-compatible)
# ---------------------------------------------------------------------------

def _make_app() -> object:
    """Build and return a configured HermesApp instance."""
    _require_textual()
    return HermesApp()


def run() -> None:
    """Entry point called by ``hermes tui``; builds and runs HermesApp."""
    _require_textual()
    HermesApp().run()
