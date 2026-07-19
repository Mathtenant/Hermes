"""Task store + WBS tree — Phase 2.5.

Public API:
    Task, NodeKind, TaskUpdate  — Pydantic models (tasks/model.py)
    TaskStore                   — SQLite-backed store (tasks/store.py)
    wbs_number, progress_rollup, all_paths — tree helpers (tasks/tree.py)
"""

from hermes_assistant.tasks.model import NodeKind, Task, TaskUpdate
from hermes_assistant.tasks.store import TaskStore
from hermes_assistant.tasks.tree import all_paths, progress_rollup, wbs_number

__all__ = [
    "NodeKind",
    "Task",
    "TaskUpdate",
    "TaskStore",
    "wbs_number",
    "progress_rollup",
    "all_paths",
]
