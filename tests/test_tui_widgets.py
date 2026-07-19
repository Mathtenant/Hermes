"""Unit tests for pure rendering functions in tui.widgets (no textual required)."""

from __future__ import annotations

from datetime import date

from rich.text import Text

from hermes_assistant.tui.widgets import done_bar, gantt_row

# ---------------------------------------------------------------------------
# done_bar
# ---------------------------------------------------------------------------

class TestDoneBar:
    def test_zero_percent(self) -> None:
        bar = done_bar(0.0, width=10)
        assert bar == " " * 10

    def test_hundred_percent(self) -> None:
        bar = done_bar(100.0, width=10)
        assert bar == "█" * 10

    def test_fifty_percent(self) -> None:
        bar = done_bar(50.0, width=10)
        assert bar.count("█") == 5
        assert len(bar) == 10

    def test_width_respected(self) -> None:
        for w in (5, 10, 20):
            assert len(done_bar(70.0, width=w)) == w

    def test_clamped_above_hundred(self) -> None:
        bar = done_bar(150.0, width=8)
        assert bar == "█" * 8

    def test_clamped_below_zero(self) -> None:
        bar = done_bar(-10.0, width=8)
        assert bar == " " * 8


# ---------------------------------------------------------------------------
# gantt_row — milestones
# ---------------------------------------------------------------------------

class TestGanttRowMilestone:
    _START = date(2026, 7, 1)
    _END = date(2026, 7, 31)

    def test_milestone_at_start(self) -> None:
        bar = gantt_row(None, self._START, self._START, self._END, width=30, status="ok")
        assert isinstance(bar, Text)
        assert "◆" in bar.plain
        assert len(bar.plain) == 30

    def test_milestone_at_end(self) -> None:
        bar = gantt_row(None, self._END, self._START, self._END, width=30, status="warn")
        assert "◆" in bar.plain
        assert len(bar.plain) == 30

    def test_milestone_in_middle(self) -> None:
        mid = date(2026, 7, 15)
        bar = gantt_row(None, mid, self._START, self._END, width=30, status="ok")
        assert "◆" in bar.plain
        assert len(bar.plain) == 30

    def test_milestone_style_ok(self) -> None:
        bar = gantt_row(None, self._START, self._START, self._END, width=10, status="ok")
        assert bar.style == "green"

    def test_milestone_style_late(self) -> None:
        bar = gantt_row(None, self._START, self._START, self._END, width=10, status="late")
        assert bar.style == "red bold"

    def test_milestone_style_warn(self) -> None:
        bar = gantt_row(None, self._START, self._START, self._END, width=10, status="warn")
        assert bar.style == "yellow"

    def test_milestone_style_unknown(self) -> None:
        bar = gantt_row(None, self._START, self._START, self._END, width=10, status="future")
        assert bar.style == "default"


# ---------------------------------------------------------------------------
# gantt_row — ranged items
# ---------------------------------------------------------------------------

class TestGanttRowRanged:
    _START = date(2026, 7, 1)
    _END = date(2026, 7, 31)

    def test_ranged_bar_contains_block(self) -> None:
        item_start = date(2026, 7, 10)
        item_due = date(2026, 7, 20)
        bar = gantt_row(item_start, item_due, self._START, self._END, width=30, status="ok")
        assert "█" in bar.plain
        assert len(bar.plain) == 30

    def test_ranged_full_width(self) -> None:
        bar = gantt_row(self._START, self._END, self._START, self._END, width=20, status="ok")
        assert "█" in bar.plain
        assert len(bar.plain) == 20

    def test_width_variants(self) -> None:
        for w in (5, 10, 40, 80):
            item_start = date(2026, 7, 5)
            item_due = date(2026, 7, 25)
            bar = gantt_row(item_start, item_due, self._START, self._END, width=w, status="ok")
            assert len(bar.plain) == w

    def test_equal_start_due_treated_as_milestone(self) -> None:
        d = date(2026, 7, 15)
        bar = gantt_row(d, d, self._START, self._END, width=20, status="ok")
        assert "◆" in bar.plain

    def test_start_after_due_treated_as_milestone(self) -> None:
        bar = gantt_row(
            date(2026, 7, 20), date(2026, 7, 10),
            self._START, self._END, width=20, status="ok"
        )
        assert "◆" in bar.plain


# ---------------------------------------------------------------------------
# gantt_row — edge / invalid range
# ---------------------------------------------------------------------------

class TestGanttRowEdgeCases:
    def test_invalid_range_returns_placeholder(self) -> None:
        d = date(2026, 7, 1)
        # range_start == range_end → invalid
        bar = gantt_row(None, d, d, d, width=10, status="ok")
        assert len(bar.plain) >= 1  # should not crash

    def test_zero_width_no_crash(self) -> None:
        d = date(2026, 7, 1)
        bar = gantt_row(None, d, date(2026, 7, 1), date(2026, 7, 31), width=0, status="ok")
        assert isinstance(bar, Text)
