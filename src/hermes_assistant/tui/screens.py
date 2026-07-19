"""TUI screens for the HERMES dashboard (require textual at runtime)."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hermes_assistant.dashboard_html import DashboardData


def _require_textual() -> None:
    try:
        import textual  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            'TUI screens require textual. Install with: pip install "hermes-assistant[tui]"'
        ) from exc


# ---------------------------------------------------------------------------
# Screen 1 — Project List
# ---------------------------------------------------------------------------

def make_project_list_screen(data: DashboardData) -> object:  # type: ignore[return]
    """Factory: returns a ProjectListScreen instance (requires textual)."""
    _require_textual()
    from textual.screen import Screen  # type: ignore[import]
    from textual.widgets import DataTable, Footer  # type: ignore[import]

    from hermes_assistant.tui.models import build_project_cards
    from hermes_assistant.tui.widgets import done_bar

    class ProjectListScreen(Screen):  # type: ignore[misc]
        """Screen 1: Sortable list of all projects."""

        BINDINGS = [
            ("s", "cycle_sort", "Sort"),
            ("j", "cursor_down"),
            ("k", "cursor_up"),
            ("g", "scroll_home"),
            ("G", "scroll_end"),
        ]

        def __init__(self, dashboard_data: DashboardData) -> None:
            super().__init__()
            self._data = dashboard_data
            self._sort_by = "deadline"
            self._cards = build_project_cards(dashboard_data)

        def compose(self):  # type: ignore[override]
            table: DataTable = DataTable(id="projects-table")  # type: ignore[type-arg]
            table.cursor_type = "row"
            table.zebra_stripes = True
            yield table
            yield Footer()

        def on_mount(self) -> None:
            self._rebuild_table()

        def _sorted_cards(self):  # type: ignore[return]
            sorts = {
                "deadline": lambda c: (c.deadline or date.max, c.project_id),
                "name": lambda c: c.project_id,
                "pct": lambda c: (-c.pct_done, c.project_id),
            }
            key_fn = sorts.get(self._sort_by, sorts["deadline"])
            return sorted(self._cards, key=key_fn)

        def _rebuild_table(self) -> None:
            table = self.query_one(DataTable)
            table.clear(columns=True)
            table.add_columns("ID", "Label", "Deadline", "Done", "#Items", "#Pend", "#Rev")
            for card in self._sorted_cards():
                table.add_row(
                    card.project_id[:16],
                    card.label[:20],
                    str(card.deadline) if card.deadline else "—",
                    done_bar(card.pct_done, 10),
                    str(card.n_timeline),
                    str(card.n_pendenzen),
                    str(card.n_reviews),
                    key=card.project_id,
                )

        def action_cycle_sort(self) -> None:
            sorts = ["deadline", "name", "pct"]
            idx = sorts.index(self._sort_by) if self._sort_by in sorts else 0
            self._sort_by = sorts[(idx + 1) % len(sorts)]
            self._rebuild_table()

        def on_data_table_row_selected(self, event: object) -> None:
            project_id = event.row_key.value  # type: ignore[union-attr]
            self.app.push_screen(make_project_detail_screen(project_id, self._data))  # type: ignore[arg-type]

    return ProjectListScreen(data)


# ---------------------------------------------------------------------------
# Screen 2 — Project Detail (Timeline / Board / WBS tabs)
# ---------------------------------------------------------------------------

def make_project_detail_screen(project_id: str, data: DashboardData) -> object:
    """Factory: returns a ProjectDetailScreen instance (requires textual)."""
    _require_textual()
    from textual.containers import Vertical  # type: ignore[import]
    from textual.screen import Screen  # type: ignore[import]
    from textual.widgets import Footer, Static, TabbedContent, TabPane  # type: ignore[import]

    from hermes_assistant.tui.widgets import gantt_row

    class ProjectDetailScreen(Screen):  # type: ignore[misc]
        """Screen 2: Timeline + Board + WBS tabs for one project."""

        BINDINGS = [
            ("escape", "app.pop_screen", "Back"),
            ("q", "app.pop_screen", "Back"),
        ]

        def __init__(self, pid: str, dashboard_data: DashboardData) -> None:
            super().__init__()
            self._project_id = pid
            self._data = dashboard_data

        def compose(self):  # type: ignore[override]
            with TabbedContent():
                with TabPane("Timeline", id="tab-timeline"):
                    yield Vertical(id="timeline-pane")
                with TabPane("Board", id="tab-board"):
                    yield Vertical(id="board-pane")
                with TabPane("WBS", id="tab-wbs"):
                    yield Vertical(id="wbs-pane")
            yield Footer()

        def on_mount(self) -> None:
            self._render_timeline()
            self._render_board()
            self._render_wbs()

        def _render_timeline(self) -> None:
            pane = self.query_one("#timeline-pane", Vertical)
            entries = [e for e in self._data.timeline if e.project_id == self._project_id]
            if not entries:
                pane.mount(Static("No timeline items for this project."))
                return
            dates = [e.date for e in entries]
            try:
                r_start = date.fromisoformat(min(dates))
                r_end = date.fromisoformat(max(dates))
            except ValueError:
                pane.mount(Static("Invalid date format in timeline."))
                return
            for entry in entries:
                try:
                    item_due = date.fromisoformat(entry.date)
                except ValueError:
                    continue
                _bar = gantt_row(None, item_due, r_start, r_end, width=40, status=(
                    "ok" if entry.status == "closed" else
                    "late" if entry.status == "blocked" else "warn"
                ))
                label = f"{entry.date}  [{_bar.plain.strip() or entry.kind}]  {entry.label[:40]}"
                pane.mount(Static(label))

        def _render_board(self) -> None:
            pane = self.query_one("#board-pane", Vertical)
            for col in self._data.kanban:
                pane.mount(Static(f"[bold]{col.label}[/bold] ({len(col.cards)})"))
                for card in col.cards[:20]:
                    pane.mount(Static(f"  {card.wbs_number}  {card.title[:40]}  {card.owner or '—'}"))
                if col.overflow:
                    pane.mount(Static(f"  +{col.overflow} more…", classes="dim"))

        def _render_wbs(self) -> None:
            pane = self.query_one("#wbs-pane", Vertical)
            if not self._data.wbs:
                pane.mount(Static("No WBS nodes. Use 'hermes task-add' to create tasks."))
                return
            for node in self._data.wbs:
                self._mount_wbs_node(pane, node, indent=0)

        def _mount_wbs_node(self, parent: object, node: object, indent: int) -> None:
            prefix = "  " * indent
            status_sym = "✓" if node.status == "closed" else ("!" if node.status == "blocked" else "○")  # type: ignore[union-attr]
            label = f"{prefix}{status_sym} {node.wbs_number}  {node.title[:40]}"  # type: ignore[union-attr]
            parent.mount(Static(label))  # type: ignore[union-attr]
            for child in (node.children or []):  # type: ignore[union-attr]
                self._mount_wbs_node(parent, child, indent + 1)

    return ProjectDetailScreen(project_id, data)


# ---------------------------------------------------------------------------
# Screen 3 — Pendenzen
# ---------------------------------------------------------------------------

def make_pendenzen_screen(data: DashboardData) -> object:
    """Factory: returns a PendenzenScreen instance (requires textual)."""
    _require_textual()
    from textual.screen import Screen  # type: ignore[import]
    from textual.widgets import DataTable, Footer  # type: ignore[import]

    from hermes_assistant.tui.models import PendenzFilter

    class PendenzenScreen(Screen):  # type: ignore[misc]
        """Screen 3: Filterable list of pendenzen."""

        BINDINGS = [
            ("f", "toggle_filter", "Filter"),
            ("j", "cursor_down"),
            ("k", "cursor_up"),
        ]

        _PRIORITY_SORT = {"blocker": 0, "high": 1, "medium": 2, "low": 3}

        def __init__(self, dashboard_data: DashboardData) -> None:
            super().__init__()
            self._data = dashboard_data
            self._filter = PendenzFilter()

        def compose(self):  # type: ignore[override]
            table: DataTable = DataTable(id="pend-table")  # type: ignore[type-arg]
            table.cursor_type = "row"
            table.zebra_stripes = True
            yield table
            yield Footer()

        def on_mount(self) -> None:
            self._rebuild_table()

        def _visible_rows(self):  # type: ignore[return]
            rows = self._data.pendenzen
            f = self._filter
            if f.source:
                rows = [r for r in rows if r.source == f.source]
            if f.priority:
                rows = [r for r in rows if r.priority == f.priority]
            if f.status:
                rows = [r for r in rows if r.status == f.status]
            return sorted(rows, key=lambda r: (
                self._PRIORITY_SORT.get(r.priority, 99),
                r.due_date or "9999-99-99",
                r.id,
            ))

        def _rebuild_table(self) -> None:
            table = self.query_one(DataTable)
            table.clear(columns=True)
            table.add_columns("Title", "Source", "Priority", "Status", "Owner", "Due")
            for row in self._visible_rows():
                table.add_row(
                    row.title[:32],
                    row.source,
                    row.priority,
                    row.status,
                    row.owner or "—",
                    row.due_date or "—",
                    key=row.id,
                )

        def action_toggle_filter(self) -> None:
            self.app.push_screen(make_filter_modal(self._filter, self._on_filter_applied))

        def _on_filter_applied(self, new_filter: PendenzFilter) -> None:
            self._filter = new_filter
            self._rebuild_table()

    return PendenzenScreen(data)


# ---------------------------------------------------------------------------
# Screen 4 — Reviews
# ---------------------------------------------------------------------------

def make_reviews_screen(data: DashboardData) -> object:
    """Factory: returns a ReviewsScreen instance (requires textual)."""
    _require_textual()
    from textual.screen import Screen  # type: ignore[import]
    from textual.widgets import DataTable, Footer  # type: ignore[import]

    class ReviewsScreen(Screen):  # type: ignore[misc]
        """Screen 4: Completed review results table."""

        BINDINGS = [
            ("j", "cursor_down"),
            ("k", "cursor_up"),
        ]

        _VERDICT_STYLE = {"pass": "green", "pass_with_comments": "yellow", "fail": "red bold"}

        def __init__(self, dashboard_data: DashboardData) -> None:
            super().__init__()
            self._data = dashboard_data

        def compose(self):  # type: ignore[override]
            table: DataTable = DataTable(id="reviews-table")  # type: ignore[type-arg]
            table.cursor_type = "row"
            table.zebra_stripes = True
            yield table
            yield Footer()

        def on_mount(self) -> None:
            table = self.query_one(DataTable)
            table.add_columns("Job", "Rubric", "Verdict", "Blockers", "Majors", "Minors", "Deliverable")
            for row in self._data.reviews:
                style = self._VERDICT_STYLE.get(row.verdict, "default")
                table.add_row(
                    row.job_id[:12],
                    row.rubric_id,
                    f"[{style}]{row.verdict}[/{style}]",
                    str(row.blockers),
                    str(row.majors),
                    str(row.minors),
                    row.deliverable[:32],
                    key=row.job_id,
                )

    return ReviewsScreen(data)


# ---------------------------------------------------------------------------
# Filter Modal (used by PendenzenScreen)
# ---------------------------------------------------------------------------

def make_filter_modal(
    current_filter: object,
    on_apply: object,
) -> object:
    """Factory: returns a FilterModal ModalScreen instance (requires textual)."""
    _require_textual()
    from textual.containers import Vertical  # type: ignore[import]
    from textual.screen import ModalScreen  # type: ignore[import]
    from textual.widgets import Button, Label, Select  # type: ignore[import]

    from hermes_assistant.tui.models import PendenzFilter

    class FilterModal(ModalScreen):  # type: ignore[misc]
        """Modal dialog for PendenzFilter configuration."""

        def __init__(
            self,
            filt: PendenzFilter,
            callback: object,
        ) -> None:
            super().__init__()
            self._filter = filt
            self._callback = callback

        def compose(self):  # type: ignore[override]
            with Vertical(id="filter-dialog"):
                yield Label("Filter Pendenzen")
                yield Select(
                    [("All", ""), ("manual", "manual"), ("review", "review"),
                     ("meeting", "meeting"), ("decision", "decision")],
                    value=self._filter.source or "",
                    id="filter-source",
                    prompt="Source",
                )
                yield Select(
                    [("All", ""), ("blocker", "blocker"), ("high", "high"),
                     ("medium", "medium"), ("low", "low")],
                    value=self._filter.priority or "",
                    id="filter-priority",
                    prompt="Priority",
                )
                yield Select(
                    [("All", ""), ("open", "open"), ("closed", "closed"), ("blocked", "blocked")],
                    value=self._filter.status or "",
                    id="filter-status",
                    prompt="Status",
                )
                yield Button("Apply", id="apply-btn", variant="primary")
                yield Button("Clear", id="clear-btn")

        def on_button_pressed(self, event: object) -> None:
            btn_id = event.button.id  # type: ignore[union-attr]
            if btn_id == "clear-btn":
                new_f = PendenzFilter()
            else:
                src_val = self.query_one("#filter-source", Select).value  # type: ignore[attr-defined]
                pri_val = self.query_one("#filter-priority", Select).value  # type: ignore[attr-defined]
                st_val = self.query_one("#filter-status", Select).value  # type: ignore[attr-defined]
                new_f = PendenzFilter(
                    source=src_val or None,
                    priority=pri_val or None,
                    status=st_val or None,
                )
            self.dismiss()
            self._callback(new_f)  # type: ignore[operator]

    return FilterModal(current_filter, on_apply)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Help Modal
# ---------------------------------------------------------------------------

def make_help_modal() -> object:
    """Factory: returns a HelpModal ModalScreen instance (requires textual)."""
    _require_textual()
    from textual.containers import Vertical  # type: ignore[import]
    from textual.screen import ModalScreen  # type: ignore[import]
    from textual.widgets import Button, Markdown  # type: ignore[import]

    _help_text = """\
# HERMES TUI — Keyboard Reference

| Key | Action |
|-----|--------|
| `1` | Projects list |
| `2` | Project detail (from list row) |
| `3` | Pendenzen |
| `4` | Reviews |
| `r` | Refresh data |
| `d` | Toggle dark/light theme |
| `s` | Cycle sort (Project list) |
| `f` | Filter (Pendenzen) |
| `j/k` | Move cursor down/up |
| `g/G` | Jump to first/last row |
| `Enter` | Select / drill down |
| `Esc/q` | Go back / quit |
| `?` | This help |
"""

    class HelpModal(ModalScreen):  # type: ignore[misc]
        """Full-screen keyboard reference."""

        def compose(self):  # type: ignore[override]
            with Vertical(id="help-dialog"):
                yield Markdown(_help_text)
                yield Button("Close", id="close-btn", variant="primary")

        def on_button_pressed(self, event: object) -> None:
            self.dismiss()

    return HelpModal()
