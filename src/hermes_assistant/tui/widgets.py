"""Custom Textual widgets and pure rendering functions.

Pure functions (gantt_row, done_bar) have no Textual imports and are
fully unit-testable. Textual widget classes are imported lazily so the
module can be imported even when textual is not installed (the classes
themselves will fail to instantiate at runtime without textual).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from rich.text import Text

if TYPE_CHECKING:
    pass  # textual imports deferred to class bodies


# ---------------------------------------------------------------------------
# Pure rendering helpers (no textual dependency)
# ---------------------------------------------------------------------------

def done_bar(pct: float, width: int = 10) -> str:
    """Render a fixed-width progress bar using block characters.

    Args:
        pct:   Completion percentage 0–100.
        width: Total character width of the bar.

    Returns:
        A string of ``width`` characters: filled blocks + spaces.
    """
    filled = max(0, min(width, round(pct / 100 * width)))
    return "█" * filled + " " * (width - filled)


def gantt_row(
    item_start: date | None,
    item_due: date,
    range_start: date,
    range_end: date,
    width: int,
    status: str,
) -> Text:
    """Render a single Gantt bar as a Rich Text object (pure, unit-testable).

    Milestones (item_start is None or equals item_due) are rendered as a
    single ``◆`` character.  Ranged items are rendered as a block bar ``█``.
    Colour reflects status: ok=green, warn=yellow, late=red.

    Args:
        item_start: Inclusive start date (None for milestones).
        item_due:   Due/end date.
        range_start: Left edge of the full Gantt timeline.
        range_end:   Right edge of the full Gantt timeline.
        width:       Character width of the rendered bar.
        status:      "ok" | "warn" | "late" | anything (→ default style).

    Returns:
        A ``rich.text.Text`` object exactly ``width`` characters wide.
    """
    if range_start >= range_end or width <= 0:
        return Text("?" * max(1, width), style="dim")

    total_days = (range_end - range_start).days
    style_map = {"ok": "green", "warn": "yellow", "late": "red bold"}
    style = style_map.get(status, "default")

    is_milestone = item_start is None or item_start >= item_due
    if is_milestone:
        due_frac = (item_due - range_start).days / total_days
        col = max(0, min(width - 1, int(due_frac * (width - 1))))
        bar = " " * col + "◆" + " " * (width - col - 1)
    else:
        start_frac = (item_start - range_start).days / total_days
        due_frac = (item_due - range_start).days / total_days
        start_col = max(0, min(width - 1, int(start_frac * (width - 1))))
        due_col = max(start_col, min(width - 1, int(due_frac * (width - 1))))
        bar_len = max(1, due_col - start_col + 1)
        bar = " " * start_col + "█" * bar_len
        bar = bar[:width].ljust(width)

    return Text(bar[:width], style=style)


# ---------------------------------------------------------------------------
# Textual widget classes (require textual at runtime)
# ---------------------------------------------------------------------------

def _require_textual() -> None:
    """Raise ImportError with install hint if textual is not available."""
    try:
        import textual  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            'TUI widgets require textual. Install with: pip install "hermes-assistant[tui]"'
        ) from exc


class GanttRowWidget:
    """Display a single Gantt row (label + bar).

    Wraps a Textual Static widget.  Instantiation raises ImportError when
    textual is not installed.
    """

    def __new__(cls, title: str, bar: Text, **kwargs: object) -> GanttRowWidget:  # type: ignore[misc]
        _require_textual()
        from textual.widgets import Static  # type: ignore[import]

        class _GanttRowWidgetImpl(Static):  # type: ignore[misc]
            def __init__(self, title: str, bar: Text, **kw: object) -> None:
                super().__init__(**kw)
                self._title = title
                self._bar = bar

            def render(self) -> Text:
                label = Text(self._title[:20].ljust(20))
                label.append_text(self._bar)
                return label

        return _GanttRowWidgetImpl(title, bar, **kwargs)  # type: ignore[return-value]


class KanbanCardWidget:
    """A focusable Kanban card.

    Wraps a Textual Static widget.  Instantiation raises ImportError when
    textual is not installed.
    """

    def __new__(  # type: ignore[misc]
        cls,
        task_id: str,
        title: str,
        owner: str | None,
        due: date | None,
        **kwargs: object,
    ) -> KanbanCardWidget:
        _require_textual()
        from textual.widgets import Static  # type: ignore[import]

        class _KanbanCardWidgetImpl(Static):  # type: ignore[misc]
            can_focus = True

            def __init__(
                self,
                task_id: str,
                title: str,
                owner: str | None,
                due: date | None,
                **kw: object,
            ) -> None:
                super().__init__(**kw)
                self.task_id = task_id
                self._title = title
                self._owner = owner or "—"
                self._due = due

            def render(self) -> Text:
                content = Text(f"{self._title[:20]}\n{self._owner}", style="dim")
                if self._due:
                    content.append(f"\n{self._due}", style="yellow")
                return content

        return _KanbanCardWidgetImpl(task_id, title, owner, due, **kwargs)  # type: ignore[return-value]
