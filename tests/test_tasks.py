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


def test_update_accepts_a_plain_date_field() -> None:
    """`update(due_date=date(...))` used to raise inside json.dumps.

    ``_ISOEncoder`` handled ``datetime`` but not ``date``. ``datetime`` is a
    subclass of ``date`` and not the reverse, so a plain ``date`` — what
    ``Pendenz.due_date`` holds — fell through to the base encoder and raised
    TypeError. Creation never hit it because pydantic serialises the model
    itself; only ``update()``, which passes raw values to ``json.dumps``, did.
    Nothing updated a due date until the Beschlussliste import did.
    """
    from datetime import date as _date

    from hermes_assistant.tasks.pendenzen import Pendenz

    store = TaskStore(":memory:")
    try:
        pid = store.create(Pendenz(id="", title="Vertrag prüfen"))
        store.update(pid, due_date=_date(2026, 9, 30))
        assert str(store.get(pid).due_date) == "2026-09-30"
    finally:
        store.close()


def test_update_keeps_the_time_component_of_a_datetime() -> None:
    """The date arm must not shadow datetime and truncate it."""
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    store = TaskStore(":memory:")
    try:
        tid = store.create(Task(id="", title="X"))
        store.update(tid, raised_at=_dt(2026, 9, 30, 14, 25, tzinfo=_UTC))
        assert "14:25" in str(store.get(tid).raised_at)
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Soft delete & restore
#
# TaskStore grew but never shrank: it had create, update and close_task, and no
# way at all to remove a row. Deletion is soft so that the dashboard's Undo can
# actually restore rather than re-create from remembered fields.
# ---------------------------------------------------------------------------


def _store_with_tree() -> tuple[TaskStore, str, str, str, str]:
    """root → kid → grandkid, plus an unrelated sibling root."""
    store = TaskStore(":memory:")
    root = store.create(Task(id="", title="Root"))
    kid = store.create(Task(id="", title="Kid", parent_id=root))
    grandkid = store.create(Task(id="", title="Grandkid", parent_id=kid))
    other = store.create(Task(id="", title="Other"))
    return store, root, kid, grandkid, other


def test_soft_delete_hides_the_task() -> None:
    store, root, _, _, _ = _store_with_tree()
    try:
        store.soft_delete(root)
        assert store.get(root) is None
    finally:
        store.close()


def test_soft_delete_keeps_the_row_for_restore() -> None:
    """The blob is untouched, which is what makes restore a true inverse."""
    store, root, _, _, _ = _store_with_tree()
    try:
        store.soft_delete(root)
        hidden = store.get(root, include_deleted=True)
        assert hidden is not None
        assert hidden.title == "Root"
    finally:
        store.close()


def test_soft_delete_takes_the_whole_subtree() -> None:
    """A visible child under a deleted parent would be orphaned in every view."""
    store, root, kid, grandkid, _ = _store_with_tree()
    try:
        ids = store.soft_delete(root)
        assert set(ids) == {root, kid, grandkid}
        assert store.get(grandkid) is None
    finally:
        store.close()


def test_soft_delete_returns_ids_parent_first() -> None:
    store, root, _, _, _ = _store_with_tree()
    try:
        assert store.soft_delete(root)[0] == root
    finally:
        store.close()


def test_soft_delete_leaves_unrelated_tasks_alone() -> None:
    store, root, _, _, other = _store_with_tree()
    try:
        store.soft_delete(root)
        assert store.get(other) is not None
    finally:
        store.close()


def test_deleted_tasks_do_not_count_as_open() -> None:
    store, root, _, _, _ = _store_with_tree()
    try:
        before = store.count_open()
        store.soft_delete(root)
        assert store.count_open() == before - 3
    finally:
        store.close()


def test_deleted_tasks_vanish_from_list_by_parent() -> None:
    store, root, kid, _, _ = _store_with_tree()
    try:
        store.soft_delete(kid)
        assert [t.id for t in store.list_by_parent(root)] == []
    finally:
        store.close()


def test_deleted_tasks_vanish_from_the_tree() -> None:
    store, root, _, _, _ = _store_with_tree()
    try:
        store.soft_delete(root)
        assert [c["id"] for c in store.tree()["children"]] != [root]
    finally:
        store.close()


def test_restore_is_the_inverse_of_soft_delete() -> None:
    store, root, kid, grandkid, _ = _store_with_tree()
    try:
        before = store.count_open()
        store.restore(store.soft_delete(root))
        assert store.count_open() == before
        assert store.get(grandkid) is not None
    finally:
        store.close()


def test_soft_delete_raises_for_an_unknown_id() -> None:
    store = TaskStore(":memory:")
    try:
        with pytest.raises(KeyError):
            store.soft_delete("nope")
    finally:
        store.close()


def test_deleting_a_child_then_its_parent_does_not_widen_the_undo() -> None:
    """Undoing the parent must not resurrect a child deleted earlier, on purpose."""
    store, root, kid, grandkid, _ = _store_with_tree()
    try:
        store.soft_delete(kid)
        parent_ids = store.soft_delete(root)
        assert kid not in parent_ids
        assert grandkid not in parent_ids

        store.restore(parent_ids)
        assert store.get(root) is not None
        assert store.get(kid) is None
    finally:
        store.close()


def test_restore_ignores_ids_that_are_not_deleted() -> None:
    store, root, _, _, other = _store_with_tree()
    try:
        restored = store.restore([other, "ghost"])
        assert [t.id for t in restored] == [other]
    finally:
        store.close()


def test_find_by_external_ref_still_sees_deleted_rows() -> None:
    """It answers "is this ref in the unique index?", and the index counts them.

    Filtering here would make the importer try to INSERT a ref that already
    exists and fail on the constraint.
    """
    store = TaskStore(":memory:")
    try:
        tid = store.create(Task(id="", title="Importiert", external_ref="pd/x"))
        store.soft_delete(tid)
        assert store.get(tid) is None
        assert store.find_by_external_ref("pd/x") is not None
    finally:
        store.close()


def test_opening_a_database_created_before_soft_delete(tmp_path) -> None:
    """Upgrading an existing store must not need a manual migration.

    Every other test here uses ``:memory:``, which is always a fresh schema —
    so none of them can reach this path. The first version of the soft-delete
    change put ``CREATE INDEX ... ON tasks (deleted_at)`` in the schema script,
    which runs before the migration that adds the column: fresh databases were
    fine and every existing one failed to open at all.
    """
    import sqlite3

    db = tmp_path / "old.db"
    legacy = sqlite3.connect(db)
    legacy.executescript(
        """
        CREATE TABLE tasks (
            id           TEXT PRIMARY KEY,
            parent_id    TEXT,
            status       TEXT NOT NULL DEFAULT 'open',
            node_kind    TEXT NOT NULL DEFAULT 'task',
            blob         TEXT NOT NULL,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        );
        """
    )
    legacy.commit()
    legacy.close()

    store = TaskStore(str(db))
    try:
        tid = store.create(Task(id="", title="Von früher"))
        assert store.get(tid) is not None
        store.soft_delete(tid)
        assert store.get(tid) is None
    finally:
        store.close()
