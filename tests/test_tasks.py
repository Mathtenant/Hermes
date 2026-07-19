"""Unit tests for the Task store and WBS tree (Phase 2.5)."""

from __future__ import annotations

import pytest

from hermes_assistant.tasks.model import Task
from hermes_assistant.tasks.store import TaskStore
from hermes_assistant.tasks.tree import all_paths, progress_rollup

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def store() -> TaskStore:
    """In-memory TaskStore for isolated tests."""
    return TaskStore(":memory:")


def _task(title: str, **kwargs) -> Task:
    return Task(id="", title=title, **kwargs)


# --------------------------------------------------------------------------- #
# T1: Create & get
# --------------------------------------------------------------------------- #

def test_create_assigns_id(store: TaskStore) -> None:
    task_id = store.create(_task("Alpha"))
    assert task_id  # non-empty
    assert store.get(task_id) is not None


def test_get_returns_none_for_unknown(store: TaskStore) -> None:
    assert store.get("does-not-exist") is None


def test_create_stores_title(store: TaskStore) -> None:
    tid = store.create(_task("My milestone", node_kind="milestone"))
    task = store.get(tid)
    assert task is not None
    assert task.title == "My milestone"
    assert task.node_kind == "milestone"


# --------------------------------------------------------------------------- #
# T2: List by parent
# --------------------------------------------------------------------------- #

def test_list_by_parent_returns_direct_children(store: TaskStore) -> None:
    parent_id = store.create(_task("Parent"))
    child1 = store.create(_task("Child A", parent_id=parent_id))
    child2 = store.create(_task("Child B", parent_id=parent_id))

    children = store.list_by_parent(parent_id)
    ids = {c.id for c in children}
    assert ids == {child1, child2}


def test_list_by_parent_none_returns_roots(store: TaskStore) -> None:
    r1 = store.create(_task("Root 1"))
    r2 = store.create(_task("Root 2"))
    _ = store.create(_task("Child", parent_id=r1))

    roots = store.list_by_parent(None)
    root_ids = {t.id for t in roots}
    assert r1 in root_ids
    assert r2 in root_ids
    assert len(roots) == 2


# --------------------------------------------------------------------------- #
# T3: Update history logging
# --------------------------------------------------------------------------- #

def test_update_logs_history(store: TaskStore) -> None:
    tid = store.create(_task("Task with history"))
    store.update(tid, changed_by="alice", title="Updated title")
    task = store.get(tid)
    assert task is not None
    assert task.title == "Updated title"
    assert len(task.updates) == 1
    entry = task.updates[0]
    assert entry.field == "title"
    assert entry.old_value == "Task with history"
    assert entry.new_value == "Updated title"
    assert entry.changed_by == "alice"


def test_update_no_log_when_value_unchanged(store: TaskStore) -> None:
    tid = store.create(_task("Stable"))
    store.update(tid, changed_by="system", title="Stable")
    task = store.get(tid)
    assert task is not None
    assert len(task.updates) == 0   # no change recorded


def test_close_task_logs_status_change(store: TaskStore) -> None:
    tid = store.create(_task("Closeable"))
    store.close_task(tid, changed_by="bot")
    task = store.get(tid)
    assert task is not None
    assert task.status == "closed"
    assert any(u.field == "status" for u in task.updates)


# --------------------------------------------------------------------------- #
# T4: WBS numbering
# --------------------------------------------------------------------------- #

def test_wbs_root_tasks_numbered_sequentially(store: TaskStore) -> None:
    id1 = store.create(_task("Root 1"))
    id2 = store.create(_task("Root 2"))
    t1 = store.get(id1)
    t2 = store.get(id2)
    assert t1 is not None and t2 is not None
    assert t1.wbs_number == "1"
    assert t2.wbs_number == "2"


def test_wbs_children_use_parent_prefix(store: TaskStore) -> None:
    parent_id = store.create(_task("Parent"))
    c1 = store.create(_task("Child 1", parent_id=parent_id))
    c2 = store.create(_task("Child 2", parent_id=parent_id))
    child1 = store.get(c1)
    child2 = store.get(c2)
    assert child1 is not None and child2 is not None
    assert child1.wbs_number == "1.1"
    assert child2.wbs_number == "1.2"


# --------------------------------------------------------------------------- #
# T5: Progress rollup
# --------------------------------------------------------------------------- #

def test_progress_rollup_2_of_5_closed(store: TaskStore) -> None:
    parent_id = store.create(_task("Parent"))
    ids = [store.create(_task(f"Sub {i}", parent_id=parent_id)) for i in range(5)]
    # Close 2 of them.
    store.close_task(ids[0])
    store.close_task(ids[1])

    parent = store.get(parent_id)
    assert parent is not None
    result = progress_rollup(parent, store)
    assert result["total"] == 5
    assert result["closed"] == 2
    assert result["open"] == 3
    assert result["pct_done"] == pytest.approx(40.0)


def test_progress_rollup_empty_node(store: TaskStore) -> None:
    tid = store.create(_task("Leaf"))
    task = store.get(tid)
    assert task is not None
    result = progress_rollup(task, store)
    assert result["total"] == 0
    assert result["pct_done"] == 0.0


# --------------------------------------------------------------------------- #
# T6: Tree structure
# --------------------------------------------------------------------------- #

def test_tree_nests_children(store: TaskStore) -> None:
    root_id = store.create(_task("Root"))
    child_id = store.create(_task("Child", parent_id=root_id))
    _ = store.create(_task("Grandchild", parent_id=child_id))

    tree = store.tree(root_id)
    assert tree["id"] == root_id
    assert len(tree["children"]) == 1
    child_node = tree["children"][0]
    assert child_node["id"] == child_id
    assert len(child_node["children"]) == 1


def test_all_paths_leaf_only(store: TaskStore) -> None:
    tid = store.create(_task("Alone"))
    task = store.get(tid)
    assert task is not None
    paths = all_paths(task, store)
    assert len(paths) == 1
    assert paths[0][0].id == tid


def test_all_paths_branching(store: TaskStore) -> None:
    root_id = store.create(_task("Root"))
    _ = store.create(_task("Child A", parent_id=root_id))
    _ = store.create(_task("Child B", parent_id=root_id))
    root = store.get(root_id)
    assert root is not None
    paths = all_paths(root, store)
    assert len(paths) == 2  # two leaves → two paths
    for path in paths:
        assert path[0].id == root_id
