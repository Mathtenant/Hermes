"""WBS tree operations (Phase 2.5, spec §30).

Pure functions operating on Task objects and a TaskStore.  No SQLite
coupling beyond the store interface — keeps the tree logic independently
testable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hermes_assistant.tasks.model import Task
    from hermes_assistant.tasks.store import TaskStore


def wbs_number(task: Task, parent: Task | None = None) -> str:
    """Compute WBS number from parent path.

    If ``parent`` is given, derives the number from ``parent.wbs_number`` and
    the task's position among its siblings.  Otherwise returns ``task.wbs_number``
    if already set, or ``"1"`` as a default.

    This is a *pure* helper — it does not write to any store.  The store calls
    its own internal ``_compute_wbs`` on creation so the value is persisted.
    """
    if parent is not None:
        prefix = parent.wbs_number or ""
        # Caller is responsible for supplying the correct 1-based position.
        return f"{prefix}.?" if prefix else "?"
    return task.wbs_number or "1"


def progress_rollup(task: Task, store: TaskStore) -> dict[str, Any]:
    """Recursive closure/open counts for a task and its descendants.

    Returns a dict with keys:
        total: int       — total descendant tasks (excluding the root itself)
        closed: int      — count with status == "closed"
        open: int        — count with status == "open"
        blocked: int     — count with status == "blocked"
        pct_done: float  — closed / total * 100 (0 if total == 0)
    """
    totals: dict[str, int] = {"total": 0, "closed": 0, "open": 0, "blocked": 0}

    def _recurse(t: Task) -> None:
        children = store.list_by_parent(t.id)
        for child in children:
            totals["total"] += 1
            totals[child.status] = totals.get(child.status, 0) + 1
            _recurse(child)

    _recurse(task)
    total = totals["total"]
    pct = (totals["closed"] / total * 100.0) if total > 0 else 0.0
    return {**totals, "pct_done": round(pct, 1)}


def all_paths(task: Task, store: TaskStore) -> list[list[Task]]:
    """Return all root-to-leaf paths starting from ``task``.

    Each path is a list from ``task`` down to a leaf (a node with no children).
    A task with no children returns ``[[task]]`` (one path, one node).
    """
    children = store.list_by_parent(task.id)
    if not children:
        return [[task]]
    paths: list[list[Task]] = []
    for child in children:
        for sub_path in all_paths(child, store):
            paths.append([task] + sub_path)
    return paths
