"""RFC-5545 ICS export for HERMES schedules (§27, §29).

Converts one or more ``Schedule`` objects into RFC-5545 calendar files using
the ``icalendar`` library. Key invariants:

* **Confidentiality boundary** — only ``title``, ``due``, ``kind``,
  ``project_label``, and a short ``note`` appear in the ICS output.
  Deliverable content, rationale, assumptions, or reviewer reasoning are
  never included.
* **Stable UID** — ``hermes-{project_id}-{item_id}@local`` is computed
  deterministically so re-importing an updated schedule *updates* existing
  calendar entries instead of creating duplicates.
* **SEQUENCE** — sourced from ``ScheduledItem.sequence``; bump it on each
  rebuild to signal to the calendar app that the entry has changed.
* **Default VEVENT** — all-day events with ``VALARM`` reminders are the
  Outlook-safe default. ``VTODO`` is opt-in behind ``tasks_as="vtodo"``.
"""

from __future__ import annotations

from datetime import date, timedelta

from icalendar import Alarm, Calendar, Event, Todo

from hermes_assistant.scheduling.model import ItemKind, Schedule, ScheduledItem

# Never include these strings in ICS output (confidentiality enforcement).
_CONFIDENTIAL_KEYWORDS = frozenset(
    ["assumption", "rationale", "reasoning", "deliverable content", "evidence"]
)


def _assert_non_confidential(text: str, field: str) -> None:
    """Guard: raise if ``text`` contains a known confidential keyword.

    This is a belt-and-suspenders check called during ICS generation to
    enforce the confidentiality boundary (§24).
    """
    lower = text.lower()
    for kw in _CONFIDENTIAL_KEYWORDS:
        if kw in lower:
            raise ValueError(
                f"ICS {field} must not contain confidential content "
                f"(found keyword {kw!r})"
            )


def _make_valarm(lead_days: int, summary: str) -> Alarm:
    """Create a VALARM component that fires ``lead_days`` days before the event."""
    alarm = Alarm()
    alarm.add("action", "DISPLAY")
    alarm.add("description", f"Reminder: {summary}")
    alarm.add("trigger", timedelta(days=-lead_days))
    return alarm


def _item_to_vevent(item: ScheduledItem) -> Event:
    """Convert a ``ScheduledItem`` to a VEVENT component."""
    # Enforce confidentiality on every user-supplied string field.
    _assert_non_confidential(item.title, "SUMMARY")
    note = item.note or ""
    _assert_non_confidential(note, "DESCRIPTION")

    event = Event()
    event.add("summary", item.title)
    # All-day event: DTSTART;VALUE=DATE, DTEND = day + 1
    dtstart: date = item.due
    if item.start is not None:
        dtstart = item.start
    event.add("dtstart", dtstart)
    event.add("dtend", item.due + timedelta(days=1))
    event.add("uid", item.uid)
    event.add("sequence", item.sequence)
    event.add("categories", [item.project_label])

    if note:
        event.add("description", note)

    for reminder in item.reminders:
        event.add_component(_make_valarm(reminder.lead_days, item.title))

    return event


def _item_to_vtodo(item: ScheduledItem) -> Todo:
    """Convert a ``ScheduledItem`` to a VTODO component."""
    _assert_non_confidential(item.title, "SUMMARY")
    note = item.note or ""
    _assert_non_confidential(note, "DESCRIPTION")

    todo = Todo()
    todo.add("summary", item.title)
    todo.add("due", item.due)
    todo.add("uid", item.uid)
    todo.add("sequence", item.sequence)
    todo.add("categories", [item.project_label])

    if note:
        todo.add("description", note)

    return todo


def _build_calendar(
    schedule: Schedule,
    *,
    tasks_as: str,
    calendar_name: str,
) -> Calendar:
    """Build an icalendar ``Calendar`` object from one ``Schedule``."""
    cal = Calendar()
    cal.add("prodid", f"-//HERMES Assistant//{schedule.project_id}//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("x-wr-calname", calendar_name)

    for item in schedule.items:
        is_task = item.kind == ItemKind.task
        if is_task and tasks_as == "vtodo":
            cal.add_component(_item_to_vtodo(item))
        else:
            cal.add_component(_item_to_vevent(item))

    return cal


def to_ics(
    schedule: Schedule | list[Schedule],
    *,
    tasks_as: str = "events",
    merged: bool = True,
    calendar_name: str = "HERMES Assistant",
) -> dict[str, str]:
    """Export one or more schedules to ICS text.

    Parameters
    ----------
    schedule:
        A single ``Schedule`` or a list for multi-project export.
    tasks_as:
        ``"events"`` (Outlook-safe default) — task items become all-day
        ``VEVENT``\\s with alarms.
        ``"vtodo"`` — task items become ``VTODO`` components (Apple/Thunderbird).
    merged:
        If ``True`` (default) all projects go into one ``.ics`` file
        (``"hermes_combined.ics"``). If ``False``, each project gets its
        own file keyed by ``{project_id}.ics``.
    calendar_name:
        ``X-WR-CALNAME`` value — the display name in the calendar app.

    Returns
    -------
    dict[str, str]
        Mapping of filename → ICS text content.
    """
    schedules: list[Schedule] = (
        [schedule] if isinstance(schedule, Schedule) else schedule
    )

    if merged or len(schedules) == 1:
        # Merge all items into one calendar.
        cal = Calendar()
        cal.add("prodid", "-//HERMES Assistant//merged//EN")
        cal.add("version", "2.0")
        cal.add("calscale", "GREGORIAN")
        cal.add("x-wr-calname", calendar_name)
        for sched in schedules:
            inner = _build_calendar(sched, tasks_as=tasks_as, calendar_name=calendar_name)
            for component in inner.walk():
                if component.name in ("VEVENT", "VTODO"):
                    cal.add_component(component)
        filename = "hermes_combined.ics" if len(schedules) > 1 else f"{schedules[0].project_id}.ics"
        return {filename: cal.to_ical().decode("utf-8")}
    else:
        result: dict[str, str] = {}
        for sched in schedules:
            inner = _build_calendar(sched, tasks_as=tasks_as, calendar_name=calendar_name)
            result[f"{sched.project_id}.ics"] = inner.to_ical().decode("utf-8")
        return result
