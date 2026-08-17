"""State snapshots and invariant checks for edge-case simulations.

``snapshot()`` fingerprints every table in a SQLite file (row count + content
checksum, volatile ``updated_at`` excluded, plus per-plan version sequences)
so two points in time can be diffed with :func:`reconcile`. ``assert_invariants``
re-derives the domain rules each store's public API is supposed to enforce
(enum membership, numeric ranges, timestamp ordering, FK integrity, contiguous
version numbering) directly from the raw table via :func:`~tests.sim.faults.raw_conn`
— so it catches violations even when they were written by a path that bypassed
the store's Python-level guards (e.g. the bulk importer's raw ``INSERT OR
REPLACE``).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .faults import raw_conn

_VOLATILE_COLUMNS = frozenset({"updated_at"})

_VALID_RISK_SEVERITIES = {"low", "medium", "high", "critical"}
_VALID_RISK_STATUSES = {"open", "mitigated", "accepted", "closed"}
_VALID_TASK_STATUSES = {"open", "closed", "blocked"}


# --------------------------------------------------------------------------- #
# Snapshot
# --------------------------------------------------------------------------- #


def _table_names(conn: Any) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return [r[0] for r in rows]


def snapshot(db_path: str | Path) -> dict[str, Any]:
    """Return a dict fingerprinting every table in *db_path*.

    For each table: ``{"count": int, "checksum": str, "columns": [...]}``.
    Tables that carry both a ``plan_id`` and a ``version`` column additionally
    get ``"version_sequences": {plan_id: [versions...]}`` so callers can
    assert contiguity/monotonicity directly (S2).
    """
    result: dict[str, Any] = {}
    with raw_conn(db_path, read_only=True) as conn:
        for table in _table_names(conn):
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
            checksum_cols = [c for c in cols if c not in _VOLATILE_COLUMNS] or cols
            col_list = ", ".join(checksum_cols)
            rows = conn.execute(f"SELECT {col_list} FROM {table} ORDER BY rowid").fetchall()
            h = hashlib.sha256()
            for row in rows:
                h.update(repr(tuple(row)).encode("utf-8"))
            entry: dict[str, Any] = {
                "count": len(rows),
                "checksum": h.hexdigest(),
                "columns": checksum_cols,
            }
            if "plan_id" in cols and "version" in cols:
                seqs: dict[str, list[int]] = {}
                for (pid,) in conn.execute(f"SELECT DISTINCT plan_id FROM {table}"):
                    versions = [
                        r[0]
                        for r in conn.execute(
                            f"SELECT version FROM {table} WHERE plan_id = ? ORDER BY version",
                            (pid,),
                        )
                    ]
                    seqs[pid] = versions
                entry["version_sequences"] = seqs
            result[table] = entry
    return result


def reconcile(
    before: dict[str, Any], after: dict[str, Any], expected_delta: dict[str, int]
) -> list[str]:
    """Diff two snapshots; flag any table whose row-count delta is wrong.

    ``expected_delta`` maps table name -> expected ``after.count -
    before.count``; tables not listed default to an expected delta of 0. This
    is the "did a silent failure lose or duplicate rows" canary: a batch
    write that reports success but only partially committed shows a
    row-count delta smaller than the caller expected.

    Returns a list of human-readable mismatch descriptions; empty means
    everything reconciled.
    """
    problems: list[str] = []
    for table in sorted(set(before) | set(after)):
        before_count = before.get(table, {}).get("count", 0)
        after_count = after.get(table, {}).get("count", 0)
        actual_delta = after_count - before_count
        expected = expected_delta.get(table, 0)
        if actual_delta != expected:
            problems.append(
                f"{table}: expected delta {expected:+d}, got {actual_delta:+d} "
                f"({before_count} -> {after_count})"
            )
    return problems


# --------------------------------------------------------------------------- #
# Invariants
# --------------------------------------------------------------------------- #


def assert_invariants(store: Any) -> None:
    """Re-derive and assert domain invariants directly from *store*'s table(s).

    Dispatches on the store's class name (duck-typed — ``tests/sim`` must not
    unconditionally import every store module). Raises ``AssertionError``
    listing every violation found (not just the first) if anything is
    inconsistent.
    """
    kind = type(store).__name__
    db_path = store.db_path
    problems: list[str] = []

    with raw_conn(db_path, read_only=True) as conn:
        if kind == "RiskRegistry":
            problems += _check_risks(conn)
        elif kind == "PlanEditor":
            problems += _check_plans(conn)
        elif kind == "TaskStore":
            problems += _check_tasks(conn)
        elif kind == "ChatStore":
            problems += _check_chat(conn)
        else:
            raise ValueError(f"assert_invariants: unsupported store type {kind!r}")

    if problems:
        raise AssertionError(
            f"{kind} invariant violation(s):\n" + "\n".join(f"  - {p}" for p in problems)
        )


def _check_risks(conn: Any) -> list[str]:
    problems: list[str] = []
    rows = conn.execute(
        "SELECT id, severity, likelihood, status, created_at, updated_at, external_ref "
        "FROM risks"
    ).fetchall()
    seen_refs: dict[str, str] = {}
    for row in rows:
        rid = row["id"]
        if row["severity"] not in _VALID_RISK_SEVERITIES:
            problems.append(f"risk {rid}: invalid severity {row['severity']!r}")
        if row["status"] not in _VALID_RISK_STATUSES:
            problems.append(f"risk {rid}: invalid status {row['status']!r}")
        if not (1 <= row["likelihood"] <= 5):
            problems.append(f"risk {rid}: likelihood {row['likelihood']!r} out of range 1-5")
        if row["created_at"] is not None and row["updated_at"] is not None:
            if row["updated_at"] < row["created_at"]:
                problems.append(f"risk {rid}: updated_at < created_at")
        ext = row["external_ref"]
        if ext is not None:
            if ext in seen_refs:
                problems.append(
                    f"risk {rid}: duplicate external_ref {ext!r} (also on {seen_refs[ext]})"
                )
            seen_refs[ext] = rid
    return problems


def _check_plans(conn: Any) -> list[str]:
    problems: list[str] = []
    plan_ids = [r[0] for r in conn.execute("SELECT DISTINCT plan_id FROM plan_versions")]
    for pid in plan_ids:
        versions = [
            r[0]
            for r in conn.execute(
                "SELECT version FROM plan_versions WHERE plan_id = ? ORDER BY version",
                (pid,),
            )
        ]
        if len(versions) != len(set(versions)):
            problems.append(f"plan {pid}: duplicate version numbers {versions}")
        unique_sorted = sorted(set(versions))
        expected = list(range(1, len(unique_sorted) + 1))
        if unique_sorted != expected:
            problems.append(
                f"plan {pid}: version sequence not contiguous from 1: {unique_sorted}"
            )
    return problems


def _check_tasks(conn: Any) -> list[str]:
    problems: list[str] = []
    ids = {r[0] for r in conn.execute("SELECT id FROM tasks")}
    for row in conn.execute("SELECT id, parent_id, status FROM tasks"):
        if row["parent_id"] is not None and row["parent_id"] not in ids:
            problems.append(f"task {row['id']}: parent_id {row['parent_id']!r} does not exist")
        if row["status"] not in _VALID_TASK_STATUSES:
            problems.append(f"task {row['id']}: invalid status {row['status']!r}")
    return problems


def _check_chat(conn: Any) -> list[str]:
    problems: list[str] = []
    session_ids = {r[0] for r in conn.execute("SELECT id FROM chat_sessions")}
    for row in conn.execute("SELECT id, session_id FROM chat_messages"):
        if row["session_id"] not in session_ids:
            problems.append(f"message {row['id']}: orphaned session_id {row['session_id']!r}")
    for row in conn.execute("SELECT id, session_id FROM chat_actions"):
        if row["session_id"] not in session_ids:
            problems.append(f"action {row['id']}: orphaned session_id {row['session_id']!r}")
    return problems
