"""SQLite-backed versioned plan editor for HERMES projects.

Each call to ``update`` creates a new immutable version snapshot. The editor
supports full version history, structured diffs between any two versions,
item reordering, and role assignment. The underlying store serialises plan
items as JSON blobs to keep the schema simple.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from hermes_assistant.plans.model import PlanDiff, PlanItem, PlanItemStatus, PlanVersion

_SCHEMA = """
CREATE TABLE IF NOT EXISTS plan_versions (
    plan_id    TEXT NOT NULL,
    version    INTEGER NOT NULL,
    items_json TEXT NOT NULL,
    author     TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (plan_id, version)
);
CREATE INDEX IF NOT EXISTS idx_pv_plan_id ON plan_versions (plan_id);
"""


class PlanNotFoundError(KeyError):
    """Raised when a plan_id has no versions in the store."""


class PlanVersionNotFoundError(KeyError):
    """Raised when a specific (plan_id, version) does not exist."""


class PlanEditor:
    """Versioned plan editor backed by SQLite.

    ``":memory:"`` is accepted as db_path for isolated tests.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _row_to_version(self, row: sqlite3.Row) -> PlanVersion:
        items = [PlanItem(**d) for d in json.loads(row["items_json"])]
        return PlanVersion(
            plan_id=row["plan_id"],
            version=row["version"],
            items=items,
            author=row["author"],
            created_at=row["created_at"],
        )

    def _next_version(self, plan_id: str) -> int:
        row = self._conn.execute(
            "SELECT MAX(version) AS v FROM plan_versions WHERE plan_id = ?",
            (plan_id,),
        ).fetchone()
        cur = row["v"] if row and row["v"] is not None else 0
        return cur + 1

    def _insert_version(self, pv: PlanVersion) -> None:
        from datetime import UTC, datetime

        created_at = pv.created_at or datetime.now(UTC).isoformat()
        self._conn.execute(
            "INSERT INTO plan_versions (plan_id, version, items_json, author, created_at) "
            "VALUES (?,?,?,?,?)",
            (
                pv.plan_id,
                pv.version,
                json.dumps([item.model_dump() for item in pv.items]),
                pv.author,
                created_at,
            ),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def create(
        self,
        plan_id: str,
        items: list[PlanItem],
        *,
        author: str = "",
    ) -> PlanVersion:
        """Create a new plan (version 1) with the given items."""
        pv = PlanVersion(plan_id=plan_id, version=1, items=items, author=author)
        self._insert_version(pv)
        return pv

    def update(
        self,
        plan_id: str,
        items: list[PlanItem],
        *,
        author: str = "",
    ) -> PlanVersion:
        """Save a new version of an existing plan.

        Raises ``PlanNotFoundError`` if the plan has never been created.
        """
        if self.get(plan_id) is None:
            raise PlanNotFoundError(plan_id)
        version = self._next_version(plan_id)
        pv = PlanVersion(plan_id=plan_id, version=version, items=items, author=author)
        self._insert_version(pv)
        return pv

    def reorder(
        self,
        plan_id: str,
        item_ids: list[str],
        *,
        author: str = "",
    ) -> PlanVersion:
        """Reorder items in the latest version and save as a new version.

        Items not in ``item_ids`` are appended at the end in their original
        relative order.
        """
        latest = self.get(plan_id)
        if latest is None:
            raise PlanNotFoundError(plan_id)
        by_id = {item.id: item for item in latest.items}
        reordered: list[PlanItem] = []
        for idx, iid in enumerate(item_ids):
            if iid in by_id:
                item = by_id.pop(iid)
                item.order = idx
                reordered.append(item)
        # append remaining items not covered by item_ids
        for item in latest.items:
            if item.id in by_id:
                reordered.append(by_id.pop(item.id))
        return self.update(plan_id, reordered, author=author)

    def delete(self, plan_id: str) -> bool:
        """Remove all versions of a plan; returns True if anything was deleted."""
        cur = self._conn.execute(
            "DELETE FROM plan_versions WHERE plan_id = ?", (plan_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get(self, plan_id: str, version: int | None = None) -> PlanVersion | None:
        """Return the latest version (or a specific version) of a plan."""
        if version is None:
            row = self._conn.execute(
                "SELECT plan_id, version, items_json, author, created_at "
                "FROM plan_versions WHERE plan_id = ? "
                "ORDER BY version DESC LIMIT 1",
                (plan_id,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT plan_id, version, items_json, author, created_at "
                "FROM plan_versions WHERE plan_id = ? AND version = ?",
                (plan_id, version),
            ).fetchone()
        return self._row_to_version(row) if row else None

    def list_versions(self, plan_id: str) -> list[PlanVersion]:
        """Return all versions of a plan, oldest first."""
        rows = self._conn.execute(
            "SELECT plan_id, version, items_json, author, created_at "
            "FROM plan_versions WHERE plan_id = ? ORDER BY version ASC",
            (plan_id,),
        ).fetchall()
        return [self._row_to_version(r) for r in rows]

    def list_plans(self) -> list[str]:
        """Return all distinct plan IDs stored in this editor."""
        rows = self._conn.execute(
            "SELECT DISTINCT plan_id FROM plan_versions ORDER BY plan_id"
        ).fetchall()
        return [r["plan_id"] for r in rows]

    def diff(self, plan_id: str, v1: int, v2: int) -> PlanDiff:
        """Compute a structured diff between two versions of a plan.

        Raises ``PlanVersionNotFoundError`` if either version does not exist.
        """
        old = self.get(plan_id, v1)
        new = self.get(plan_id, v2)
        if old is None:
            raise PlanVersionNotFoundError(f"{plan_id}@v{v1}")
        if new is None:
            raise PlanVersionNotFoundError(f"{plan_id}@v{v2}")

        old_by_id = {item.id: item for item in old.items}
        new_by_id = {item.id: item for item in new.items}

        added = [item for item in new.items if item.id not in old_by_id]
        removed = [item for item in old.items if item.id not in new_by_id]
        changed = []
        for item_id, new_item in new_by_id.items():
            if item_id in old_by_id:
                old_item = old_by_id[item_id]
                if old_item.model_dump() != new_item.model_dump():
                    changed.append((old_item, new_item))

        old_order = [item.id for item in old.items if item.id in new_by_id]
        new_order = [item.id for item in new.items if item.id in old_by_id]
        reordered = old_order != new_order

        return PlanDiff(
            plan_id=plan_id,
            from_version=v1,
            to_version=v2,
            added=added,
            removed=removed,
            changed=changed,
            reordered=reordered,
        )
