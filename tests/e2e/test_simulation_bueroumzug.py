"""E2E simulation harness: Büroumzug & IT-Migration over 42 simulated days.

Architecture — Mode A (headless pytest):
    Single-process synchronous harness that drives TUI state via Textual's
    ``async with app.run_test()`` context and reads dashboard data through
    ``app._data`` directly.  The virtual clock is controlled by
    ``app._injected_now`` (Seam 2).  Auto-refresh timer is disabled via
    ``app._disable_auto_refresh = True`` (Seam 3).  Negative-float items
    render as "blocked" status via the schedule.json seam (Seam 1).

Checkpoints (8 total):
    Day  3  — project skeleton seeded; TUI discovers 1 project, 0 timeline items
    Day  7  — schedule with 4 negative-float items seeded; 4 blocked in TUI
    Day 12  — virtual clock reveals 3 items now 'closed'
    Day 16  — 2 pendenzen added; TUI shows 2 open
    Day 18  — 1 pendenz closed; TUI shows 1 open; 6 items now closed
    Day 25  — virtual clock advance; closed count confirmed stable at 6
    Day 35  — IT-Migration (Sep 3) tip-point; 7 items closed
    Day 42  — all pendenzen closed; 8 items closed; 4 blocked persists

Run:
    pytest tests/e2e/test_simulation_bueroumzug.py -q

HTML report (Mode C):
    HERMES_SIM_REPORT=1 pytest tests/e2e/test_simulation_bueroumzug.py -q
"""

from __future__ import annotations

import importlib.util
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

_TEXTUAL_INSTALLED = importlib.util.find_spec("textual") is not None

pytestmark = pytest.mark.skipif(
    not _TEXTUAL_INSTALLED,
    reason="textual not installed — skip E2E simulation harness "
    "(pip install 'hermes-assistant[tui]')",
)

if _TEXTUAL_INSTALLED:
    from hermes_assistant.tui.app import HermesApp  # noqa: E402 (conditional)

# ---------------------------------------------------------------------------
# Fixture location
# ---------------------------------------------------------------------------

_FIXTURES = Path(__file__).parent / "fixtures" / "bueroumzug"

# ---------------------------------------------------------------------------
# anyio backend (restrict to asyncio — Textual uses asyncio internally)
# ---------------------------------------------------------------------------


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


# ---------------------------------------------------------------------------
# Simulation workspace fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def sim_workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated tmp workspace with monkeypatched settings.

    Creates::
        <tmp>/
          projects/
            bueroumzug-muristrasse/
              plan.json          (copied from fixture)
          tasks.db               (created on first write)
          jobs.db                (created on first write)

    Monkeypatches ``settings.projects_path``, ``tasks_db_path``, and
    ``queue_db_path`` to point at this workspace.
    """
    from hermes_assistant.config import settings

    projects_dir = tmp_path / "projects"
    project_dir = projects_dir / "bueroumzug-muristrasse"
    project_dir.mkdir(parents=True)

    # Seed plan.json from fixture so the project is discoverable
    plan_src = _FIXTURES / "plan.json"
    (project_dir / "plan.json").write_bytes(plan_src.read_bytes())

    tasks_db = tmp_path / "tasks.db"
    jobs_db = tmp_path / "jobs.db"

    monkeypatch.setattr(settings, "projects_path", str(projects_dir))
    monkeypatch.setattr(settings, "tasks_db_path", str(tasks_db))
    monkeypatch.setattr(settings, "queue_db_path", str(jobs_db))

    return tmp_path


# ---------------------------------------------------------------------------
# Schedule builder — pre-computed fixture with 4 negative-float items
# ---------------------------------------------------------------------------


def _build_schedule() -> Any:
    """Return a Schedule with 12 items, 4 having negative float.

    Timeline (project starts 2026-08-01, hard deadline 2026-09-12):

    Regular items (closed/future based on virtual clock):
        ms_kickoff              milestone  2026-08-05
        oc_projektauftrag       task       2026-08-10
        oc_raumkonzept          task       2026-08-11
        oc_it_konzept           task       2026-08-12
        oc_kommunikation        task       2026-08-13
        ms_plan_complete        milestone  2026-08-17
        oc_it_migration         task       2026-09-03
        oc_umzug_durchgefuehrt  task       2026-09-07

    Negative-float items (always "blocked", exceeding the deadline):
        ms_umzug                milestone  2026-09-15
        oc_abnahme              task       2026-09-16
        oc_schlussbericht       task       2026-09-19
        ms_projektabschluss     milestone  2026-09-22
    """
    from datetime import date

    from hermes_assistant.scheduling.model import ItemKind, Schedule, ScheduledItem

    pid = "bueroumzug-muristrasse"
    label = "Buerozumzug Muristrasse"

    def _item(
        item_id: str, title: str, kind: ItemKind, due: date
    ) -> ScheduledItem:
        return ScheduledItem(
            uid=f"hermes-bm-{item_id}@local",
            project_id=pid,
            project_label=label,
            item_id=item_id,
            title=title,
            kind=kind,
            due=due,
        )

    return Schedule(
        project_id=pid,
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
        items=[
            _item("ms_kickoff", "Kickoff", ItemKind.milestone, date(2026, 8, 5)),
            _item("oc_projektauftrag", "Projektauftrag", ItemKind.task, date(2026, 8, 10)),
            _item("oc_raumkonzept", "Raumkonzept", ItemKind.task, date(2026, 8, 11)),
            _item("oc_it_konzept", "IT-Migrationskonzept", ItemKind.task, date(2026, 8, 12)),
            _item("oc_kommunikation", "Kommunikationsplan", ItemKind.task, date(2026, 8, 13)),
            _item("ms_plan_complete", "Planung abgeschlossen", ItemKind.milestone, date(2026, 8, 17)),
            _item("oc_it_migration", "IT-Migration", ItemKind.task, date(2026, 9, 3)),
            _item("oc_umzug_durchgefuehrt", "Umzug durchgefuehrt", ItemKind.task, date(2026, 9, 7)),
            # Negative-float: due dates exceed the hard deadline (2026-09-12)
            _item("ms_umzug", "Umzug abgeschlossen", ItemKind.milestone, date(2026, 9, 15)),
            _item("oc_abnahme", "Abnahme", ItemKind.task, date(2026, 9, 16)),
            _item("oc_schlussbericht", "Schlussbericht", ItemKind.task, date(2026, 9, 19)),
            _item("ms_projektabschluss", "Projektabschluss", ItemKind.milestone, date(2026, 9, 22)),
        ],
        negative_float=[
            "ms_umzug",
            "oc_abnahme",
            "oc_schlussbericht",
            "ms_projektabschluss",
        ],
    )


# ---------------------------------------------------------------------------
# Introspection helpers (read from app._data, not from rendered widgets)
# ---------------------------------------------------------------------------


def _projects_shown(app: Any) -> int:
    """Number of projects in the current dashboard snapshot."""
    return len(app._data.projects) if app._data else 0


def _timeline_count(app: Any) -> int:
    """Total timeline entries in the current dashboard snapshot."""
    return len(app._data.timeline) if app._data else 0


def _blocked_count(app: Any) -> int:
    """Timeline entries with status='blocked' (negative-float items)."""
    if app._data is None:
        return 0
    return sum(1 for e in app._data.timeline if e.status == "blocked")


def _closed_count(app: Any) -> int:
    """Timeline entries with status='closed' (due date passed virtual clock)."""
    if app._data is None:
        return 0
    return sum(1 for e in app._data.timeline if e.status == "closed")


def _pendenzen_open(app: Any) -> int:
    """Pendenzen with status='open'."""
    if app._data is None:
        return 0
    return sum(1 for p in app._data.pendenzen if p.status == "open")


def _pendenzen_total(app: Any) -> int:
    """Total pendenzen count."""
    return len(app._data.pendenzen) if app._data else 0


# ---------------------------------------------------------------------------
# Mode C: HTML simulation report (compiled when HERMES_SIM_REPORT=1)
# ---------------------------------------------------------------------------


class SimulationReport:
    """Accumulates checkpoint snapshots and emits an HTML report."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self._checkpoints: list[dict[str, Any]] = []

    def add(self, day: int, sim_date: datetime, metrics: dict[str, Any]) -> None:
        self._checkpoints.append({"day": day, "date": str(sim_date.date()), **metrics})

    def write_html(self) -> Path:
        rows = "\n".join(
            "<tr>"
            f"<td>Day {cp['day']}</td>"
            f"<td>{cp['date']}</td>"
            f"<td>{cp.get('projects_shown', '-')}</td>"
            f"<td>{cp.get('timeline_items', '-')}</td>"
            f"<td>{cp.get('blocked_count', '-')}</td>"
            f"<td>{cp.get('closed_count', '-')}</td>"
            f"<td>{cp.get('pendenzen_open', '-')}</td>"
            "</tr>"
            for cp in self._checkpoints
        )
        html = (
            "<!DOCTYPE html><html lang='en'><head>"
            "<meta charset='utf-8'>"
            "<title>HERMES E2E Simulation Report — Buerozumzug Muristrasse</title>"
            "<style>body{font-family:sans-serif;margin:2rem}"
            "table{border-collapse:collapse;width:100%}"
            "th,td{border:1px solid #ccc;padding:.5rem;text-align:left}"
            "th{background:#f0f0f0}</style></head><body>"
            "<h1>E2E Simulation Report: Buerozumzug & IT-Migration</h1>"
            "<p>42-day virtual clock simulation with 8 checkpoints.</p>"
            "<table><thead><tr>"
            "<th>Checkpoint</th><th>Sim Date</th>"
            "<th>Projects</th><th>Timeline</th>"
            "<th>Blocked (negative-float)</th><th>Closed</th><th>Pendenzen open</th>"
            f"</tr></thead><tbody>{rows}</tbody></table></body></html>"
        )
        out = self.output_dir / "simulation_report.html"
        out.write_text(html, encoding="utf-8")
        return out


# ---------------------------------------------------------------------------
# Main E2E test — 8 checkpoints, all assertions green
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_simulation_bueroumzug_complete(sim_workdir: Path) -> None:
    """Drive 42-day Büroumzug simulation: 8 checkpoints, all green.

    Each checkpoint:
    1. Advances the virtual clock (Seam 2).
    2. Optionally seeds/modifies on-disk data.
    3. Forces a TUI refresh via ``pilot.press("r")`` (Seam 3 ensures no
       auto-timer interference).
    4. Asserts dashboard metrics from ``app._data`` (Seam 1 checked at Day 7).
    """
    from hermes_assistant.config import settings
    from hermes_assistant.tasks.pendenzen import Pendenz, PendenzSource
    from hermes_assistant.tasks.store import TaskStore

    project_dir = Path(settings.projects_path) / "bueroumzug-muristrasse"
    report_mode = bool(os.environ.get("HERMES_SIM_REPORT"))
    report = SimulationReport(sim_workdir) if report_mode else None

    # Open a TaskStore for direct writes (shares the monkeypatched DB)
    ts = TaskStore(settings.tasks_db_path)
    p1_id = ""
    p2_id = ""

    app = HermesApp()
    app._disable_auto_refresh = True  # Seam 3: no timer

    async with app.run_test(size=(120, 40)) as pilot:

        # ------------------------------------------------------------------
        # Day 3 — project directory seeded; no schedule.json yet
        # ------------------------------------------------------------------
        app._injected_now = datetime(2026, 8, 3, tzinfo=UTC)
        await pilot.press("r")
        await pilot.pause()

        assert _projects_shown(app) == 1, (
            "Day 3: expected 1 project in dashboard, "
            f"got {_projects_shown(app)}"
        )
        assert _timeline_count(app) == 0, (
            "Day 3: no schedule.json yet — expected 0 timeline items, "
            f"got {_timeline_count(app)}"
        )
        if report:
            report.add(3, datetime(2026, 8, 3, tzinfo=UTC), {
                "projects_shown": _projects_shown(app),
                "timeline_items": _timeline_count(app),
            })

        # ------------------------------------------------------------------
        # Day 7 — schedule.json seeded with 4 negative-float items
        #          CORE ASSERTION: Seam 1 marks them "blocked"
        # ------------------------------------------------------------------
        sched = _build_schedule()
        (project_dir / "schedule.json").write_text(
            sched.model_dump_json(indent=2), encoding="utf-8"
        )
        app._injected_now = datetime(2026, 8, 7, tzinfo=UTC)
        await pilot.press("r")
        await pilot.pause()

        assert _timeline_count(app) == 12, (
            f"Day 7: expected 12 timeline items, got {_timeline_count(app)}"
        )
        assert _blocked_count(app) == 4, (
            "Day 7: CORE ASSERTION — expected 4 negative-float items with "
            f"status='blocked', got {_blocked_count(app)}"
        )
        if report:
            report.add(7, datetime(2026, 8, 7, tzinfo=UTC), {
                "timeline_items": _timeline_count(app),
                "blocked_count": _blocked_count(app),
            })

        # ------------------------------------------------------------------
        # Day 12 — virtual clock reveals 3 items as 'closed'
        #   ms_kickoff (Aug 5), oc_projektauftrag (Aug 10), oc_raumkonzept (Aug 11)
        # ------------------------------------------------------------------
        app._injected_now = datetime(2026, 8, 12, tzinfo=UTC)
        await pilot.press("r")
        await pilot.pause()

        assert _closed_count(app) == 3, (
            f"Day 12: expected 3 items closed (due < Aug 12), got {_closed_count(app)}"
        )
        assert _blocked_count(app) == 4, (
            f"Day 12: negative-float count unchanged, got {_blocked_count(app)}"
        )
        if report:
            report.add(12, datetime(2026, 8, 12, tzinfo=UTC), {
                "closed_count": _closed_count(app),
                "blocked_count": _blocked_count(app),
            })

        # ------------------------------------------------------------------
        # Day 16 — 2 pendenzen added to TaskStore
        #   Also 5 items now closed (adds oc_it_konzept Aug 12, oc_kommunikation Aug 13)
        # ------------------------------------------------------------------
        p1_id = ts.create(
            Pendenz(
                id="",
                title="IT Lizenzen besorgen",
                source=PendenzSource.manual,
                priority="high",
            )
        )
        p2_id = ts.create(
            Pendenz(
                id="",
                title="Schluessel uebergeben",
                source=PendenzSource.manual,
                priority="medium",
            )
        )

        app._injected_now = datetime(2026, 8, 16, tzinfo=UTC)
        await pilot.press("r")
        await pilot.pause()

        assert _pendenzen_total(app) == 2, (
            f"Day 16: expected 2 pendenzen total, got {_pendenzen_total(app)}"
        )
        assert _pendenzen_open(app) == 2, (
            f"Day 16: expected 2 open pendenzen, got {_pendenzen_open(app)}"
        )
        assert _closed_count(app) == 5, (
            f"Day 16: expected 5 items closed (due < Aug 16), got {_closed_count(app)}"
        )
        if report:
            report.add(16, datetime(2026, 8, 16, tzinfo=UTC), {
                "closed_count": _closed_count(app),
                "pendenzen_total": _pendenzen_total(app),
                "pendenzen_open": _pendenzen_open(app),
            })

        # ------------------------------------------------------------------
        # Day 18 — 1 pendenz closed; ms_plan_complete (Aug 17) now also closed
        # ------------------------------------------------------------------
        ts.update(p1_id, status="closed")

        app._injected_now = datetime(2026, 8, 18, tzinfo=UTC)
        await pilot.press("r")
        await pilot.pause()

        assert _pendenzen_open(app) == 1, (
            f"Day 18: expected 1 open pendenz (p1 closed), got {_pendenzen_open(app)}"
        )
        assert _closed_count(app) == 6, (
            f"Day 18: expected 6 items closed (adds ms_plan_complete Aug 17), "
            f"got {_closed_count(app)}"
        )
        if report:
            report.add(18, datetime(2026, 8, 18, tzinfo=UTC), {
                "closed_count": _closed_count(app),
                "pendenzen_open": _pendenzen_open(app),
            })

        # ------------------------------------------------------------------
        # Day 25 — clock confirms 6 closed; oc_it_migration (Sep 3) still future
        # ------------------------------------------------------------------
        app._injected_now = datetime(2026, 8, 25, tzinfo=UTC)
        await pilot.press("r")
        await pilot.pause()

        assert _closed_count(app) == 6, (
            f"Day 25: expected 6 items closed (oc_it_migration Sep 3 still future), "
            f"got {_closed_count(app)}"
        )
        assert _blocked_count(app) == 4, (
            f"Day 25: negative-float stable at 4, got {_blocked_count(app)}"
        )
        if report:
            report.add(25, datetime(2026, 8, 25, tzinfo=UTC), {
                "closed_count": _closed_count(app),
                "blocked_count": _blocked_count(app),
            })

        # ------------------------------------------------------------------
        # Day 35 (sim_date Sep 4) — oc_it_migration (Sep 3) tips to 'closed'
        # ------------------------------------------------------------------
        app._injected_now = datetime(2026, 9, 4, tzinfo=UTC)
        await pilot.press("r")
        await pilot.pause()

        assert _closed_count(app) == 7, (
            "Day 35: expected 7 items closed "
            f"(oc_it_migration Sep 3 now closed), got {_closed_count(app)}"
        )
        if report:
            report.add(35, datetime(2026, 9, 4, tzinfo=UTC), {
                "closed_count": _closed_count(app),
                "blocked_count": _blocked_count(app),
            })

        # ------------------------------------------------------------------
        # Day 42 (sim_date Sep 11) — oc_umzug (Sep 7) closed; all pendenzen closed
        # ------------------------------------------------------------------
        ts.update(p2_id, status="closed")

        app._injected_now = datetime(2026, 9, 11, tzinfo=UTC)
        await pilot.press("r")
        await pilot.pause()

        assert _pendenzen_open(app) == 0, (
            f"Day 42: expected 0 open pendenzen (audit trail complete), "
            f"got {_pendenzen_open(app)}"
        )
        assert _closed_count(app) == 8, (
            "Day 42: expected 8 items closed "
            f"(oc_umzug Sep 7 now closed), got {_closed_count(app)}"
        )
        assert _blocked_count(app) == 4, (
            "Day 42: 4 negative-float items remain blocked "
            f"(they exceed the deadline), got {_blocked_count(app)}"
        )
        if report:
            report.add(42, datetime(2026, 9, 11, tzinfo=UTC), {
                "closed_count": _closed_count(app),
                "blocked_count": _blocked_count(app),
                "pendenzen_open": _pendenzen_open(app),
            })

    # Mode C: write HTML report if requested
    if report:
        out = report.write_html()
        print(f"\nSimulation report written to: {out}")
