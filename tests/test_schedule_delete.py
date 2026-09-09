"""Tests for deleting one dated obligation from a project's plan.

The list on Planung merges two stores — to-dos from the task database, and
dated items swept out of each project's ``schedule.json`` — and offered the
same delete button on every row. Only the to-dos could honour it: the other
rows went to ``DELETE /api/tasks/<id>`` with an id that store has never seen,
and came back "Task not found" with the row still on screen.

What these tests hold is less the happy path than the three things that make a
destructive edit to somebody's own plan file safe: the id cannot escape the
projects root, undo puts the row back where it WAS, and undoing twice does not
duplicate it.
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from hermes_assistant.webapp.server import app

client = TestClient(app, raise_server_exceptions=False)


def _schedule(*item_ids: str):
    from hermes_assistant.scheduling.model import Schedule, ScheduledItem

    return Schedule(
        project_id="widget",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        items=[
            ScheduledItem(
                uid=f"hermes-widget-{i}@local", project_id="widget",
                project_label="Widget", item_id=i, title=f"Task {i.upper()}",
                kind="task", due=date(2026, 6, 1),
            )
            for i in item_ids
        ],
        negative_float=list(item_ids[:1]),
    )


@pytest.fixture()
def plan(tmp_path: Path):
    """A project holding a three-item schedule.json."""
    proj = tmp_path / "projects"
    (proj / "widget").mkdir(parents=True)
    f = proj / "widget" / "schedule.json"
    f.write_text(_schedule("a", "b", "c").model_dump_json(indent=2), encoding="utf-8")
    with patch("hermes_assistant.webapp.server.settings.projects_path", str(proj)):
        yield f


def _ids(f: Path) -> list[str]:
    from hermes_assistant.scheduling.model import Schedule

    return [i.item_id for i in Schedule.model_validate_json(f.read_text()).items]


def _delete(item: str = "b"):
    return client.delete(f"/api/schedule/widget/items/{item}")


# --------------------------------------------------------------------------- #
# The delete
# --------------------------------------------------------------------------- #


def test_a_plan_item_can_be_deleted(plan: Path) -> None:
    resp = _delete("b")
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] == 1
    assert _ids(plan) == ["a", "c"]


def test_the_task_route_is_not_the_one_that_answers(plan: Path) -> None:
    """The bug, pinned: a schedule item's id is not a task id, and sending it
    to the task store is how "Task not found" reached the screen."""
    assert client.delete("/api/tasks/b").status_code == 404


def test_deleting_drops_a_dangling_negative_float_entry(plan: Path) -> None:
    """negative_float names item_ids; a leftover would keep colouring a row
    that no longer exists."""
    from hermes_assistant.scheduling.model import Schedule

    assert "a" in Schedule.model_validate_json(plan.read_text()).negative_float
    assert _delete("a").status_code == 200
    assert Schedule.model_validate_json(plan.read_text()).negative_float == []


def test_an_unknown_item_is_a_404_not_a_silent_success(plan: Path) -> None:
    assert _delete("nosuch").status_code == 404
    assert _ids(plan) == ["a", "b", "c"]


def test_a_project_without_a_schedule_is_a_404(plan: Path) -> None:
    assert client.delete("/api/schedule/nosuch/items/b").status_code == 404


@pytest.mark.parametrize("bad", ["../etc", "..", "a/b", "not a slug", "."])
def test_the_project_id_cannot_climb_out_of_the_projects_root(
    plan: Path, bad: str
) -> None:
    """Two different mechanisms reject these, and the test should not care
    which: anything carrying a slash or a dot segment fails to match the route
    at all (405), and what does match meets the importer's own path guard
    (422). What matters is that none of them reaches the filesystem.
    """
    resp = client.delete(f"/api/schedule/{bad}/items/b")
    assert resp.status_code in (404, 405, 422), resp.text
    assert _ids(plan) == ["a", "b", "c"]


def test_a_slug_shaped_but_invalid_project_id_meets_the_path_guard(
    plan: Path,
) -> None:
    """The case that actually reaches the handler — the one the guard is for.

    Without this the parametrised test above would pass on 405 alone, proving
    only that Starlette rejects slashes, and the guard could be deleted
    without a single test noticing.
    """
    resp = client.delete("/api/schedule/not a slug/items/b")
    assert resp.status_code == 422, resp.text


def test_the_file_survives_being_rewritten(plan: Path) -> None:
    """A half-written schedule.json takes the whole dashboard down with a
    parse error, which is worse than losing the edit."""
    _delete("b")
    json.loads(plan.read_text(encoding="utf-8"))   # still valid JSON
    assert not list(plan.parent.glob("*.tmp"))     # and no debris left behind


# --------------------------------------------------------------------------- #
# Undo
# --------------------------------------------------------------------------- #


def test_undo_puts_the_row_back_where_it_was(plan: Path) -> None:
    """Re-appending would silently reorder a plan somebody arranged, and an
    undo that does not undo is worse than no undo."""
    undo = _delete("b").json()["undo"]
    assert _ids(plan) == ["a", "c"]

    resp = client.post("/api/schedule/restore", json=undo)
    assert resp.status_code == 200, resp.text
    assert resp.json()["restored"] == 1
    assert _ids(plan) == ["a", "b", "c"]


def test_undo_restores_the_whole_item_not_just_its_id(plan: Path) -> None:
    from hermes_assistant.scheduling.model import Schedule

    before = Schedule.model_validate_json(plan.read_text()).items[1]
    client.post("/api/schedule/restore", json=_delete("b").json()["undo"])
    after = Schedule.model_validate_json(plan.read_text()).items[1]
    assert after == before


def test_undoing_twice_does_not_duplicate_the_row(plan: Path) -> None:
    """Restoring is "make sure this is present", not "insert one more" — the
    row can also have come back on its own via a re-import."""
    undo = _delete("b").json()["undo"]
    client.post("/api/schedule/restore", json=undo)
    second = client.post("/api/schedule/restore", json=undo)
    assert second.status_code == 200
    assert second.json()["restored"] == 0
    assert _ids(plan) == ["a", "b", "c"]


def test_a_deleted_last_row_comes_back_last(plan: Path) -> None:
    client.post("/api/schedule/restore", json=_delete("c").json()["undo"])
    assert _ids(plan) == ["a", "b", "c"]


def test_restore_rejects_a_body_that_is_not_a_schedule_item(plan: Path) -> None:
    resp = client.post(
        "/api/schedule/restore",
        json={"project_id": "widget", "index": 0, "item": {"nope": 1}},
    )
    assert resp.status_code == 422


def test_restore_guards_the_project_id_too(plan: Path) -> None:
    undo = _delete("b").json()["undo"]
    undo["project_id"] = "../escape"
    assert client.post("/api/schedule/restore", json=undo).status_code == 422
