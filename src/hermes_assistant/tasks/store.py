"""SQLite-backed task store (Phase 2.5, spec §30).

Mirrors the pattern of :mod:`hermes_assistant.jobqueue.jobs` — a thin typed
wrapper over a WAL-mode SQLite file.  Tasks are serialised as JSON blobs to
keep the schema stable as the Pydantic model evolves.

Schema: one ``tasks`` table with indexed (parent_id, status) for tree queries.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hermes_assistant.tasks.model import Task, TaskUpdate


class _ISOEncoder(json.JSONEncoder):
    """JSON encoder that serialises datetime/date to ISO 8601 strings."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def _now() -> datetime:
    return datetime.now(UTC)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id           TEXT PRIMARY KEY,
    parent_id    TEXT,
    status       TEXT NOT NULL DEFAULT 'open',
    node_kind    TEXT NOT NULL DEFAULT 'task',
    blob         TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    external_ref TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks (parent_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status);
"""


class TaskStore:
    """Typed wrapper over the SQLite ``tasks`` table."""

    def __init__(self, db_path: str | Path) -> None:
        """Open (creating if needed) the task database in WAL mode.

        ``:memory:`` is accepted for tests, maintaining a single shared
        connection for the store's lifetime.
        """
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._migrate()
        # RLock serialises all public method calls so that concurrent FastAPI
        # worker threads cannot interleave execute/commit sequences on the same
        # shared connection. RLock (re-entrant) is used because some public
        # methods call other public methods internally (e.g. create calls get
        # and list_by_parent, update calls get, close_task calls update,
        # tree calls list_by_parent).
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ #
    def _migrate(self) -> None:
        """Add columns introduced after initial schema creation (idempotent)."""
        existing_cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(tasks)")
        }
        if "external_ref" not in existing_cols:
            self._conn.execute("ALTER TABLE tasks ADD COLUMN external_ref TEXT")
        # Partial unique index: NULL is excluded so rows without external_ref
        # never conflict with each other.
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_external_ref "
            "ON tasks (external_ref) WHERE external_ref IS NOT NULL"
        )
        self._conn.commit()

    # ------------------------------------------------------------------ #
    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    def _task_to_blob(self, task: Task) -> str:
        return task.model_dump_json()

    def _row_to_task(self, row: sqlite3.Row) -> Task:
        return Task.model_validate_json(row["blob"])

    # ------------------------------------------------------------------ #
    def create(self, task: Task) -> str:
        """Insert a new task and return its id.

        If ``task.id`` is empty, a new UUID hex is assigned.
        If ``wbs_number`` is empty, it is computed from parent position.
        """
        with self._lock:
            if not task.id:
                task = task.model_copy(update={"id": uuid.uuid4().hex})
            if not task.wbs_number:
                task = task.model_copy(update={"wbs_number": self._compute_wbs(task)})
            now = _now()
            task = task.model_copy(update={"created_at": now, "updated_at": now})

            ext_ref = task.external_ref or None
            self._conn.execute(
                "INSERT INTO tasks "
                "(id, parent_id, status, node_kind, blob, created_at, updated_at, external_ref) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task.id,
                    task.parent_id,
                    task.status,
                    task.node_kind,
                    self._task_to_blob(task),
                    now.isoformat(),
                    now.isoformat(),
                    ext_ref,
                ),
            )
            # Register this child in its parent's children_ids.
            if task.parent_id:
                parent = self.get(task.parent_id)
                if parent is not None:
                    new_children = list(parent.children_ids) + [task.id]
                    self._update_blob(parent.id, {"children_ids": new_children})
            self._conn.commit()
            return task.id

    def get(self, task_id: str) -> Task | None:
        """Fetch a task by id, or ``None`` if not found."""
        with self._lock:
            row = self._conn.execute(
                "SELECT blob FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            return self._row_to_task(row) if row else None

    def find_by_external_ref(self, external_ref: str) -> Task | None:
        """Find a task by its Copilot export key (idempotency look-up).

        Returns the stored task, or ``None`` if no row has that external_ref.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT blob FROM tasks WHERE external_ref = ?",
                (external_ref,),
            ).fetchone()
            return self._row_to_task(row) if row else None

    def count_open(self) -> int:
        """Return the number of tasks currently in ``open`` status.

        Uses the indexed ``status`` column, so this stays cheap even as the
        tree grows. Used by :class:`ChatService` (Phase 6 M10) to hydrate
        chat context without loading the full tree.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status = 'open'"
            ).fetchone()
            return int(row[0]) if row else 0

    def list_by_parent(self, parent_id: str | None) -> list[Task]:
        """Return all direct children of ``parent_id`` (or roots if ``None``)."""
        with self._lock:
            if parent_id is None:
                rows = self._conn.execute(
                    "SELECT blob FROM tasks WHERE parent_id IS NULL ORDER BY created_at ASC"
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT blob FROM tasks WHERE parent_id = ? ORDER BY created_at ASC",
                    (parent_id,),
                ).fetchall()
            return [self._row_to_task(r) for r in rows]

    def update(self, task_id: str, changed_by: str = "system", **fields: Any) -> Task:
        """Update named fields on a task, logging each change as a TaskUpdate.

        Returns the updated task.  Raises ``KeyError`` if task not found.
        """
        with self._lock:
            task = self.get(task_id)
            if task is None:
                raise KeyError(f"Task {task_id!r} not found")
            now = _now()
            new_updates = list(task.updates)
            for field, new_val in fields.items():
                old_val = getattr(task, field, None)
                if old_val != new_val:
                    new_updates.append(
                        TaskUpdate(
                            timestamp=now,
                            field=field,
                            old_value=old_val,
                            new_value=new_val,
                            changed_by=changed_by,
                        )
                    )
            merged: dict[str, Any] = {**fields, "updates": new_updates, "updated_at": now}
            self._update_blob(task_id, merged)
            # Keep indexed columns in sync for status changes.
            if "status" in fields:
                self._conn.execute(
                    "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                    (fields["status"], now.isoformat(), task_id),
                )
            self._conn.commit()
            result = self.get(task_id)
            assert result is not None
            return result

    def set_parent(
        self, task_id: str, new_parent_id: str | None, changed_by: str = "system"
    ) -> Task:
        """Move a task to a different parent, keeping every index consistent.

        ``update()`` deliberately cannot do this: it writes the blob and syncs
        only the ``status`` column, so assigning ``parent_id`` through it would
        leave the indexed column — the one ``list_by_parent`` reads — pointing
        at the old parent. The tree would then render in its previous shape
        while the stored blob claimed otherwise.

        Moving a node means four things must change together: the indexed
        column, the blob, both parents' ``children_ids``, and the WBS numbers
        of the moved subtree (which are derived from the parent's).

        Raises ``KeyError`` if the task or the new parent does not exist, and
        ``ValueError`` if the move would make a node its own ancestor.
        """
        with self._lock:
            task = self.get(task_id)
            if task is None:
                raise KeyError(f"Task {task_id!r} not found")
            if task.parent_id == new_parent_id:
                return task

            if new_parent_id is not None:
                if self.get(new_parent_id) is None:
                    raise KeyError(f"New parent {new_parent_id!r} not found")
                # Walk up from the target: if we meet the node being moved, the
                # move would detach the subtree into a cycle.
                cursor: str | None = new_parent_id
                while cursor is not None:
                    if cursor == task_id:
                        raise ValueError(
                            f"Cannot move {task_id!r} under its own descendant"
                        )
                    parent = self.get(cursor)
                    cursor = parent.parent_id if parent else None

            old_parent_id = task.parent_id
            now = _now()

            self._conn.execute(
                "UPDATE tasks SET parent_id = ?, updated_at = ? WHERE id = ?",
                (new_parent_id, now.isoformat(), task_id),
            )
            self._update_blob(
                task_id,
                {
                    "parent_id": new_parent_id,
                    "updated_at": now,
                    "updates": [
                        *task.updates,
                        TaskUpdate(
                            timestamp=now,
                            field="parent_id",
                            old_value=old_parent_id,
                            new_value=new_parent_id,
                            changed_by=changed_by,
                        ),
                    ],
                },
            )

            # Detach from the old parent, attach to the new one.
            if old_parent_id:
                old_parent = self.get(old_parent_id)
                if old_parent is not None:
                    self._update_blob(
                        old_parent_id,
                        {"children_ids": [
                            c for c in old_parent.children_ids if c != task_id
                        ]},
                    )
            if new_parent_id:
                new_parent = self.get(new_parent_id)
                if new_parent is not None and task_id not in new_parent.children_ids:
                    self._update_blob(
                        new_parent_id,
                        {"children_ids": [*new_parent.children_ids, task_id]},
                    )

            self._renumber_subtree(task_id)
            self._conn.commit()
            result = self.get(task_id)
            assert result is not None
            return result

    def _renumber_subtree(self, task_id: str) -> None:
        """Recompute wbs_number for *task_id* and everything beneath it.

        A WBS number encodes the path to the node, so moving a node invalidates
        its own number and every descendant's.
        """
        task = self.get(task_id)
        if task is None:
            return
        siblings = [t for t in self.list_by_parent(task.parent_id) if t.id != task_id]
        position = len(siblings) + 1
        if task.parent_id is None:
            number = str(position)
        else:
            parent = self.get(task.parent_id)
            prefix = parent.wbs_number if parent and parent.wbs_number else ""
            number = f"{prefix}.{position}" if prefix else str(position)
        self._update_blob(task_id, {"wbs_number": number})
        for child in self.list_by_parent(task_id):
            self._renumber_subtree(child.id)

    def close_task(self, task_id: str, changed_by: str = "system") -> Task:
        """Convenience method: set status = 'closed'."""
        with self._lock:
            return self.update(task_id, changed_by=changed_by, status="closed")

    def tree(self, root_id: str | None = None) -> dict[str, Any]:
        """Return a nested dict representation of the (sub)tree.

        ``root_id=None`` returns all root-level tasks as a list under key
        ``"children"``.  Each node has keys: id, title, node_kind, status,
        wbs_number, children (recursive).
        """
        with self._lock:
            if root_id is None:
                roots = self.list_by_parent(None)
                return {"id": None, "children": [self._node_dict(t) for t in roots]}
            task = self.get(root_id)
            if task is None:
                return {}
            return self._node_dict(task)

    # ------------------------------------------------------------------ #
    # Private helpers (called only while the lock is already held)
    # ------------------------------------------------------------------ #
    def _update_blob(self, task_id: str, fields: dict[str, Any]) -> None:
        """Merge ``fields`` into the stored blob without re-fetching the row."""
        row = self._conn.execute(
            "SELECT blob FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return
        data = json.loads(row["blob"])
        for k, v in fields.items():
            if hasattr(v, "model_dump"):
                # mode='json' converts datetime → ISO string, Enum → value, etc.
                data[k] = v.model_dump(mode="json")
            elif isinstance(v, list) and v and hasattr(v[0], "model_dump"):
                data[k] = [
                    item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                    for item in v
                ]
            else:
                data[k] = v
        now = _now().isoformat()
        data["updated_at"] = data.get("updated_at", now)
        self._conn.execute(
            "UPDATE tasks SET blob = ?, updated_at = ? WHERE id = ?",
            (json.dumps(data, cls=_ISOEncoder), now, task_id),
        )

    def _compute_wbs(self, task: Task) -> str:
        """Compute WBS number based on parent's wbs_number and sibling count."""
        siblings = self.list_by_parent(task.parent_id)
        position = len(siblings) + 1
        if task.parent_id is None:
            return str(position)
        parent = self.get(task.parent_id)
        prefix = parent.wbs_number if parent and parent.wbs_number else ""
        return f"{prefix}.{position}" if prefix else str(position)

    def _node_dict(self, task: Task) -> dict[str, Any]:
        """Recursively build a nested dict for one node."""
        children = self.list_by_parent(task.id)
        return {
            "id": task.id,
            "title": task.title,
            "node_kind": task.node_kind,
            "status": task.status,
            "wbs_number": task.wbs_number,
            "owner": task.owner,
            "children": [self._node_dict(c) for c in children],
        }
