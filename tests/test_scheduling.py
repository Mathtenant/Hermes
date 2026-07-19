"""Tests for the scheduling subsystem (Phase 3.5, §29 acceptance criteria).

All tests are deterministic and offline — no LLM, no Ollama, no network.

Coverage
--------
- Dependency topological sort (correct order + cycle detection)
- Weekend/holiday skipping (Zürich calendar + simple weekday-only mode)
- Negative-float detection when items exceed the hard deadline
- ICS confidentiality: no confidential keywords in ICS output
- Stable UID across rebuilds of the same plan
- SEQUENCE incrementing on rebuild
- Round-trip: parse exported ICS and verify date consistency
- Cross-project collision detection (deadlines module)
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from hermes_assistant.hermes.model import Milestone, Outcome, Phase, ProjectPlan
from hermes_assistant.scheduling.deadlines import cross_project_view
from hermes_assistant.scheduling.derive import (
    CyclicDependencyError,
    _Item,
    _SimpleWeekdayCal,
    derive_schedule,
    topological_sort,
)
from hermes_assistant.scheduling.ics import _CONFIDENTIAL_KEYWORDS, to_ics
from hermes_assistant.scheduling.model import (
    ItemKind,
    Reminder,
    Schedule,
    ScheduledItem,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CAL = _SimpleWeekdayCal()  # deterministic, no holiday fetching


def _make_plan(
    phases: list[tuple[str, list[tuple[str, list[str], float | None]]]]
) -> ProjectPlan:
    """Build a minimal ``ProjectPlan`` from a compact spec.

    ``phases`` is a list of ``(phase_id, [(ms_id, depends_on, effort_days), ...])``.
    """
    plan_phases: list[Phase] = []
    for phase_id, milestones in phases:
        ms_list: list[Milestone] = []
        for ms_id, deps, effort in milestones:
            ms_list.append(
                Milestone(
                    id=ms_id,
                    name=ms_id,
                    depends_on=deps,
                    effort_days=effort,
                )
            )
        plan_phases.append(Phase(id=phase_id, name=phase_id, milestones=ms_list, outcomes=[]))
    from hermes_assistant.hermes.model import Approach
    return ProjectPlan(
        title="test", scenario="test", approach=Approach.traditional,
        phases=plan_phases, roles=[],
    )


def _item(id: str, deps: list[str] | None = None, effort: float = 1.0) -> _Item:
    return _Item(id=id, title=id, kind=ItemKind.milestone, effort_days=effort, depends_on=deps or [])


def _scheduled_item(
    uid: str, project_id: str, item_id: str, due: date, kind: ItemKind = ItemKind.milestone,
    sequence: int = 0,
) -> ScheduledItem:
    return ScheduledItem(
        uid=uid, project_id=project_id, project_label=project_id,
        item_id=item_id, title=item_id, kind=kind, due=due, sequence=sequence,
    )


# ---------------------------------------------------------------------------
# Topological sort
# ---------------------------------------------------------------------------

class TestTopologicalSort:
    def test_independent_items_preserve_insertion_order(self) -> None:
        items = [_item("a"), _item("b"), _item("c")]
        result = topological_sort(items)
        assert [it.id for it in result] == ["a", "b", "c"]

    def test_simple_chain_a_then_b(self) -> None:
        items = [_item("b", deps=["a"]), _item("a")]
        result = topological_sort(items)
        ids = [it.id for it in result]
        assert ids.index("a") < ids.index("b")

    def test_diamond_dependency(self) -> None:
        #  a → b → d
        #  a → c → d
        items = [_item("a"), _item("b", ["a"]), _item("c", ["a"]), _item("d", ["b", "c"])]
        result = topological_sort(items)
        ids = [it.id for it in result]
        assert ids.index("a") < ids.index("b")
        assert ids.index("a") < ids.index("c")
        assert ids.index("b") < ids.index("d")
        assert ids.index("c") < ids.index("d")

    def test_cycle_raises(self) -> None:
        items = [_item("a", ["b"]), _item("b", ["a"])]
        with pytest.raises(CyclicDependencyError):
            topological_sort(items)

    def test_three_cycle_raises(self) -> None:
        items = [_item("a", ["c"]), _item("b", ["a"]), _item("c", ["b"])]
        with pytest.raises(CyclicDependencyError):
            topological_sort(items)

    def test_external_dependency_ignored(self) -> None:
        """depends_on referencing an id not in the item list is silently ignored."""
        items = [_item("a", ["unknown_external"])]
        result = topological_sort(items)
        assert len(result) == 1
        assert result[0].id == "a"

    def test_empty_input(self) -> None:
        assert topological_sort([]) == []


# ---------------------------------------------------------------------------
# SimpleWeekdayCal (deterministic, no network)
# ---------------------------------------------------------------------------

class TestSimpleWeekdayCal:
    def test_monday_is_working(self) -> None:
        assert _CAL.is_working_day(date(2024, 6, 3))  # Monday

    def test_saturday_not_working(self) -> None:
        assert not _CAL.is_working_day(date(2024, 6, 1))  # Saturday

    def test_sunday_not_working(self) -> None:
        assert not _CAL.is_working_day(date(2024, 6, 2))  # Sunday

    def test_add_zero_working_days_same_day(self) -> None:
        d = date(2024, 6, 3)  # Monday
        assert _CAL.add_working_days(d, 0) == d

    def test_add_1_working_day_monday_gives_tuesday(self) -> None:
        assert _CAL.add_working_days(date(2024, 6, 3), 1) == date(2024, 6, 4)

    def test_add_1_working_day_friday_gives_monday(self) -> None:
        """Friday + 1 working day must skip the weekend."""
        assert _CAL.add_working_days(date(2024, 6, 7), 1) == date(2024, 6, 10)

    def test_add_5_working_days_skips_weekend(self) -> None:
        result = _CAL.add_working_days(date(2024, 6, 3), 5)  # Mon → next Mon
        assert result == date(2024, 6, 10)


# ---------------------------------------------------------------------------
# Zürich calendar
# ---------------------------------------------------------------------------

class TestZurichCalendar:
    def test_zurich_christmas_day_not_working(self) -> None:
        from workalendar.europe import Zurich  # type: ignore[import-untyped]
        cal = Zurich()
        assert not cal.is_working_day(date(2024, 12, 25))

    def test_zurich_new_year_not_working(self) -> None:
        from workalendar.europe import Zurich  # type: ignore[import-untyped]
        cal = Zurich()
        assert not cal.is_working_day(date(2024, 1, 1))

    def test_zurich_add_working_days_skips_holiday(self) -> None:
        """Dec 24 + 3 working days should skip Dec 25 (Christmas)."""
        from workalendar.europe import Zurich  # type: ignore[import-untyped]
        cal = Zurich()
        result = cal.add_working_days(date(2024, 12, 24), 3)
        # Dec 25 (Wed) is a holiday, so 3 working days = Dec 27 (Fri)
        assert result >= date(2024, 12, 27)
        assert cal.is_working_day(result)


# ---------------------------------------------------------------------------
# derive_schedule — end-to-end
# ---------------------------------------------------------------------------

class TestDeriveSchedule:
    def test_empty_plan_returns_empty_schedule(self) -> None:
        from hermes_assistant.hermes.model import Approach
        plan = ProjectPlan(
            title="empty", scenario="s", approach=Approach.traditional,
            phases=[], roles=[],
        )
        sched = derive_schedule(
            plan, project_id="p1", project_label="P1",
            start_date=date(2024, 6, 3), calendar=_CAL,
        )
        assert sched.items == []
        assert sched.negative_float == []

    def test_single_milestone_due_after_effort(self) -> None:
        plan = _make_plan([("ph1", [("ms1", [], 3.0)])])
        sched = derive_schedule(
            plan, project_id="p1", project_label="P1",
            start_date=date(2024, 6, 3),  # Monday
            calendar=_CAL,
        )
        assert len(sched.items) == 1
        item = sched.items[0]
        assert item.due > date(2024, 6, 3)
        assert item.item_id == "ms1"
        assert item.kind == ItemKind.milestone

    def test_chain_second_milestone_after_first(self) -> None:
        plan = _make_plan([("ph1", [("ms1", [], 2.0), ("ms2", ["ms1"], 2.0)])])
        sched = derive_schedule(
            plan, project_id="p1", project_label="P1",
            start_date=date(2024, 6, 3), calendar=_CAL,
        )
        items = {it.item_id: it for it in sched.items}
        assert items["ms2"].due > items["ms1"].due

    def test_uid_format(self) -> None:
        plan = _make_plan([("ph1", [("ms1", [], 1.0)])])
        sched = derive_schedule(
            plan, project_id="myproject", project_label="My Project",
            start_date=date(2024, 6, 3), calendar=_CAL,
        )
        assert sched.items[0].uid == "hermes-myproject-ms1@local"

    def test_no_negative_float_within_deadline(self) -> None:
        plan = _make_plan([("ph1", [("ms1", [], 2.0)])])
        sched = derive_schedule(
            plan, project_id="p1", project_label="P1",
            start_date=date(2024, 6, 3),
            deadline=date(2024, 12, 31),  # very far out
            calendar=_CAL,
        )
        assert sched.negative_float == []

    def test_negative_float_when_exceeds_deadline(self) -> None:
        """An item that cannot fit before the deadline appears in negative_float."""
        plan = _make_plan([("ph1", [("ms1", [], 100.0)])])  # 100 working days
        sched = derive_schedule(
            plan, project_id="p1", project_label="P1",
            start_date=date(2024, 6, 3),
            deadline=date(2024, 6, 10),  # only 1 week
            calendar=_CAL,
        )
        assert "ms1" in sched.negative_float

    def test_cyclic_dependency_raises(self) -> None:
        plan = _make_plan([("ph1", [("ms1", ["ms2"], 1.0), ("ms2", ["ms1"], 1.0)])])
        with pytest.raises(CyclicDependencyError):
            derive_schedule(
                plan, project_id="p1", project_label="P1",
                start_date=date(2024, 6, 3), calendar=_CAL,
            )

    def test_sequence_propagated_to_items(self) -> None:
        plan = _make_plan([("ph1", [("ms1", [], 1.0)])])
        sched = derive_schedule(
            plan, project_id="p1", project_label="P1",
            start_date=date(2024, 6, 3), calendar=_CAL, sequence=3,
        )
        assert sched.items[0].sequence == 3

    def test_outcomes_with_effort_days_scheduled(self) -> None:
        """Outcomes that carry effort_days are included in the schedule."""
        from hermes_assistant.hermes.model import Approach
        oc = Outcome(id="oc1", name="Report", kind="document", mandatory=True,
                     module="m1", effort_days=2.0)
        phase = Phase(id="ph1", name="ph1", milestones=[], outcomes=[oc])
        plan = ProjectPlan(
            title="t", scenario="s", approach=Approach.traditional,
            phases=[phase], roles=[],
        )
        sched = derive_schedule(
            plan, project_id="p1", project_label="P1",
            start_date=date(2024, 6, 3), calendar=_CAL,
        )
        assert any(it.item_id == "oc1" for it in sched.items)
        assert any(it.kind == ItemKind.task for it in sched.items)


# ---------------------------------------------------------------------------
# ICS export
# ---------------------------------------------------------------------------

class TestIcsExport:
    def _simple_schedule(self, project_id: str = "proj1", sequence: int = 0) -> Schedule:
        items = [
            ScheduledItem(
                uid=f"hermes-{project_id}-ms1@local",
                project_id=project_id,
                project_label="Project One",
                item_id="ms1",
                title="Kick-off milestone",
                kind=ItemKind.milestone,
                due=date(2024, 6, 15),
                reminders=[Reminder(lead_days=5)],
                sequence=sequence,
            ),
            ScheduledItem(
                uid=f"hermes-{project_id}-task1@local",
                project_id=project_id,
                project_label="Project One",
                item_id="task1",
                title="Deliver report",
                kind=ItemKind.task,
                due=date(2024, 6, 30),
                reminders=[Reminder(lead_days=2)],
                sequence=sequence,
            ),
        ]
        return Schedule(
            project_id=project_id,
            generated_at=datetime(2024, 5, 1, 12, 0, tzinfo=UTC),
            items=items,
        )

    def test_returns_dict_with_filename(self) -> None:
        sched = self._simple_schedule()
        result = to_ics(sched)
        assert len(result) == 1
        filename = next(iter(result))
        assert filename.endswith(".ics")

    def test_ics_contains_vevent(self) -> None:
        sched = self._simple_schedule()
        ics_text = next(iter(to_ics(sched).values()))
        assert "BEGIN:VEVENT" in ics_text

    def test_ics_contains_valarm(self) -> None:
        sched = self._simple_schedule()
        ics_text = next(iter(to_ics(sched).values()))
        assert "BEGIN:VALARM" in ics_text

    def test_ics_default_tasks_as_events(self) -> None:
        """Default mode: task items become VEVENT, no VTODO."""
        sched = self._simple_schedule()
        ics_text = next(iter(to_ics(sched, tasks_as="events").values()))
        assert "BEGIN:VEVENT" in ics_text
        assert "BEGIN:VTODO" not in ics_text

    def test_ics_tasks_as_vtodo(self) -> None:
        """tasks_as='vtodo': task items become VTODO."""
        sched = self._simple_schedule()
        ics_text = next(iter(to_ics(sched, tasks_as="vtodo").values()))
        assert "BEGIN:VTODO" in ics_text

    def test_stable_uid_across_rebuilds(self) -> None:
        """The UID must be the same whether we generate sequence 0 or 1."""
        sched0 = self._simple_schedule(sequence=0)
        sched1 = self._simple_schedule(sequence=1)
        ics0 = next(iter(to_ics(sched0).values()))
        ics1 = next(iter(to_ics(sched1).values()))
        # Extract UIDs from both
        uids0 = [line for line in ics0.splitlines() if line.startswith("UID:")]
        uids1 = [line for line in ics1.splitlines() if line.startswith("UID:")]
        assert uids0 == uids1

    def test_sequence_increments_on_rebuild(self) -> None:
        """Bumping sequence changes the SEQUENCE field in the ICS output."""
        sched0 = self._simple_schedule(sequence=0)
        sched1 = self._simple_schedule(sequence=1)
        ics0 = next(iter(to_ics(sched0).values()))
        ics1 = next(iter(to_ics(sched1).values()))
        # SEQUENCE:0 in v0, SEQUENCE:1 in v1
        assert any("SEQUENCE:0" in line for line in ics0.splitlines())
        assert any("SEQUENCE:1" in line for line in ics1.splitlines())

    def test_ics_confidentiality_no_keywords(self) -> None:
        """The exported ICS must not contain any confidential keywords.

        The confidentiality boundary (§24) states only title, date, tag, and a
        short note may appear. Deliverable content, assumptions, rationale, and
        reasoning must never be present.
        """
        sched = self._simple_schedule()
        ics_text = next(iter(to_ics(sched).values())).lower()
        for keyword in _CONFIDENTIAL_KEYWORDS:
            assert keyword not in ics_text, (
                f"ICS output contained confidential keyword {keyword!r}"
            )

    def test_ics_confidentiality_raises_on_bad_title(self) -> None:
        """If a title contains a confidential keyword, to_ics raises ValueError."""
        items = [
            ScheduledItem(
                uid="hermes-p-ms@local",
                project_id="p",
                project_label="P",
                item_id="ms",
                title="review assumptions for milestone",  # contains 'assumption'
                kind=ItemKind.milestone,
                due=date(2024, 6, 15),
            )
        ]
        sched = Schedule(
            project_id="p",
            generated_at=datetime(2024, 5, 1, 12, 0, tzinfo=UTC),
            items=items,
        )
        with pytest.raises(ValueError, match="confidential"):
            to_ics(sched)

    def test_ics_date_in_output(self) -> None:
        sched = self._simple_schedule()
        ics_text = next(iter(to_ics(sched).values()))
        assert "20240615" in ics_text

    def test_ics_categories_tag(self) -> None:
        """CATEGORIES field carries the project_label."""
        sched = self._simple_schedule()
        ics_text = next(iter(to_ics(sched).values()))
        assert "Project One" in ics_text

    def test_round_trip_parse_dates(self) -> None:
        """Parse the emitted ICS and verify the due date round-trips correctly."""
        from icalendar import Calendar  # type: ignore[import-untyped]

        sched = self._simple_schedule()
        ics_text = next(iter(to_ics(sched).values()))
        cal = Calendar.from_ical(ics_text)

        event_dates: list[date] = []
        for component in cal.walk():
            if component.name == "VEVENT":
                dtstart = component.get("dtstart")
                if dtstart:
                    dt = dtstart.dt
                    if isinstance(dt, date):
                        event_dates.append(dt)

        assert date(2024, 6, 15) in event_dates or date(2024, 6, 30) in event_dates

    def test_multi_project_merged(self) -> None:
        sched1 = self._simple_schedule("proj1")
        sched2 = self._simple_schedule("proj2")
        result = to_ics([sched1, sched2], merged=True)
        assert len(result) == 1
        ics_text = next(iter(result.values()))
        assert "proj1" in ics_text
        assert "proj2" in ics_text

    def test_multi_project_split(self) -> None:
        sched1 = self._simple_schedule("proj1")
        sched2 = self._simple_schedule("proj2")
        result = to_ics([sched1, sched2], merged=False)
        assert len(result) == 2
        assert "proj1.ics" in result
        assert "proj2.ics" in result


# ---------------------------------------------------------------------------
# Deadlines module
# ---------------------------------------------------------------------------

class TestCrossProjectView:
    def _schedule(
        self, project_id: str, items: list[tuple[str, date, ItemKind]]
    ) -> Schedule:
        sched_items = [
            ScheduledItem(
                uid=f"hermes-{project_id}-{iid}@local",
                project_id=project_id,
                project_label=project_id,
                item_id=iid,
                title=iid,
                kind=kind,
                due=due,
            )
            for iid, due, kind in items
        ]
        return Schedule(
            project_id=project_id,
            generated_at=datetime(2024, 5, 1, tzinfo=UTC),
            items=sched_items,
        )

    def test_upcoming_items_sorted_by_due(self) -> None:
        today = date(2024, 6, 1)
        sched = self._schedule("p1", [
            ("ms2", date(2024, 6, 5), ItemKind.milestone),
            ("ms1", date(2024, 6, 3), ItemKind.milestone),
        ])
        view = cross_project_view([sched], within_days=30, today=today)
        dues = [it.due for it in view.upcoming]
        assert dues == sorted(dues)

    def test_overdue_items_detected(self) -> None:
        today = date(2024, 6, 10)
        sched = self._schedule("p1", [
            ("ms1", date(2024, 6, 1), ItemKind.milestone),  # overdue
            ("ms2", date(2024, 6, 15), ItemKind.milestone),  # future
        ])
        view = cross_project_view([sched], within_days=30, today=today)
        assert len(view.overdue) == 1
        assert view.overdue[0].item_id == "ms1"

    def test_collision_across_projects(self) -> None:
        """Two items from different projects on the same day → collision."""
        collision_date = date(2024, 6, 15)
        sched1 = self._schedule("p1", [("ms1", collision_date, ItemKind.milestone)])
        sched2 = self._schedule("p2", [("ms1", collision_date, ItemKind.milestone)])
        view = cross_project_view([sched1, sched2], within_days=60, today=date(2024, 6, 1))
        assert len(view.collisions) >= 1

    def test_no_collision_same_project(self) -> None:
        """Two items from the same project on the same day are NOT flagged."""
        same_date = date(2024, 6, 15)
        sched = self._schedule("p1", [
            ("ms1", same_date, ItemKind.milestone),
            ("ms2", same_date, ItemKind.milestone),
        ])
        view = cross_project_view([sched], within_days=60, today=date(2024, 6, 1))
        assert view.collisions == []

    def test_empty_schedules(self) -> None:
        view = cross_project_view([], within_days=14, today=date(2024, 6, 1))
        assert view.upcoming == []
        assert view.overdue == []
        assert view.collisions == []

    def test_within_days_window(self) -> None:
        today = date(2024, 6, 1)
        sched = self._schedule("p1", [
            ("ms1", date(2024, 6, 5), ItemKind.milestone),   # within 7 days
            ("ms2", date(2024, 6, 20), ItemKind.milestone),  # outside 7 days
        ])
        view = cross_project_view([sched], within_days=7, today=today)
        assert len(view.upcoming) == 1
        assert view.upcoming[0].item_id == "ms1"


# ---------------------------------------------------------------------------
# Integration: plan → schedule → ICS round-trip
# ---------------------------------------------------------------------------

class TestPlanToIcsIntegration:
    def test_full_round_trip(self) -> None:
        """Build a plan, derive a schedule, export ICS, parse ICS back."""
        from icalendar import Calendar  # type: ignore[import-untyped]

        plan = _make_plan([
            ("ph1", [
                ("ms1", [], 2.0),
                ("ms2", ["ms1"], 1.0),
            ]),
        ])
        sched = derive_schedule(
            plan, project_id="integration", project_label="Integration Test",
            start_date=date(2024, 6, 3), calendar=_CAL,
        )
        assert len(sched.items) == 2
        assert sched.negative_float == []

        ics_files = to_ics(sched)
        ics_text = next(iter(ics_files.values()))
        cal = Calendar.from_ical(ics_text)

        event_summaries = [
            str(c.get("summary"))
            for c in cal.walk()
            if c.name == "VEVENT"
        ]
        assert "ms1" in event_summaries
        assert "ms2" in event_summaries

        # Dates in the ICS should all be working days (no weekend).
        for component in cal.walk():
            if component.name == "VEVENT":
                dtstart = component.get("dtstart")
                if dtstart:
                    dt = dtstart.dt
                    if isinstance(dt, date):
                        assert _CAL.is_working_day(dt), f"{dt} is not a working day"
