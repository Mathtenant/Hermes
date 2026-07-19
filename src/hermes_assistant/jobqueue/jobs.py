"""SQLite-backed job store for the async critic queue.

Heavy reviews run out-of-band so the interactive CLI never blocks on
bandwidth-bound inference. The store is a single WAL-mode SQLite file with one
``jobs`` table. Claiming is atomic via ``UPDATE ... RETURNING`` on the oldest
pending row, so multiple workers never grab the same job. Crash recovery is a
``requeue_stale`` sweep that returns orphaned ``running`` jobs to ``pending``.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel


class JobStatus(str, Enum):
    """Lifecycle state of a queued job."""

    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class Job(BaseModel):
    """One unit of queued work (currently: a rubric review)."""

    id: str
    kind: str  # "review"
    status: JobStatus
    deliverable_path: str
    rubric_id: str
    rubric_version: str | None = None
    samples: int = 3
    panel: bool = False  # Phase 5: use diverse panel instead of single-judge
    attempts: int = 0
    max_attempts: int = 3
    result_json: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str


_COLUMNS = (
    "id, kind, status, deliverable_path, rubric_id, rubric_version, "
    "samples, panel, attempts, max_attempts, result_json, error, created_at, updated_at"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    kind            TEXT NOT NULL,
    status          TEXT NOT NULL,
    deliverable_path TEXT NOT NULL,
    rubric_id       TEXT NOT NULL,
    rubric_version  TEXT,
    samples         INTEGER NOT NULL DEFAULT 3,
    panel           INTEGER NOT NULL DEFAULT 0,
    attempts        INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 3,
    result_json     TEXT,
    error           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status_created
    ON jobs (status, created_at);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class JobStore:
    """A thin, typed wrapper over the SQLite ``jobs`` table."""

    def __init__(self, db_path: str | Path) -> None:
        """Open (creating if needed) the job database in WAL mode.

        ``:memory:`` is accepted for tests, in which case a single shared
        connection is kept open for the store's lifetime.
        """
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        # WAL improves concurrent read/write; busy_timeout avoids spurious
        # "database is locked" under two workers claiming at once.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)
        # Guarded migration: add `panel` column to pre-P5 databases.
        info = self._conn.execute("PRAGMA table_info(jobs)").fetchall()
        col_names = [row[1] for row in info]
        if "panel" not in col_names:
            self._conn.execute(
                "ALTER TABLE jobs ADD COLUMN panel INTEGER NOT NULL DEFAULT 0"
            )
        self._conn.commit()

    # ------------------------------------------------------------------ #
    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            kind=row["kind"],
            status=JobStatus(row["status"]),
            deliverable_path=row["deliverable_path"],
            rubric_id=row["rubric_id"],
            rubric_version=row["rubric_version"],
            samples=row["samples"],
            panel=bool(row["panel"]),
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            result_json=row["result_json"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ------------------------------------------------------------------ #
    def enqueue(
        self,
        deliverable_path: str,
        rubric_id: str,
        *,
        kind: str = "review",
        rubric_version: str | None = None,
        samples: int = 3,
        panel: bool = False,
        max_attempts: int = 3,
    ) -> Job:
        """Insert a new ``pending`` job and return it."""
        job_id = uuid.uuid4().hex
        now = _now()
        self._conn.execute(
            f"INSERT INTO jobs ({_COLUMNS}) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, 0, ?, NULL, NULL, ?, ?)",
            (
                job_id,
                kind,
                JobStatus.pending.value,
                deliverable_path,
                rubric_id,
                rubric_version,
                samples,
                int(panel),
                max_attempts,
                now,
                now,
            ),
        )
        self._conn.commit()
        got = self.get(job_id)
        assert got is not None  # just inserted
        return got

    def claim_next(self) -> Job | None:
        """Atomically claim the oldest pending job, marking it ``running``.

        Uses ``UPDATE ... RETURNING`` on a single row so two concurrent workers
        cannot claim the same job: SQLite serialises writers and the second
        worker sees the row already out of ``pending``.
        """
        now = _now()
        cur = self._conn.execute(
            "UPDATE jobs SET status = ?, attempts = attempts + 1, updated_at = ? "
            "WHERE id = ("
            "  SELECT id FROM jobs WHERE status = ? "
            "  ORDER BY created_at ASC LIMIT 1"
            ") "
            f"RETURNING {_COLUMNS}",
            (JobStatus.running.value, now, JobStatus.pending.value),
        )
        row = cur.fetchone()
        self._conn.commit()
        return self._row_to_job(row) if row is not None else None

    def complete(self, job_id: str, result_json: str) -> None:
        """Mark a job ``done`` and store its serialised ReviewResult."""
        self._conn.execute(
            "UPDATE jobs SET status = ?, result_json = ?, error = NULL, "
            "updated_at = ? WHERE id = ?",
            (JobStatus.done.value, result_json, _now(), job_id),
        )
        self._conn.commit()

    def fail(self, job_id: str, error: str, *, retry: bool = False) -> Job | None:
        """Fail a job.

        If ``retry`` and the job still has attempts left, it returns to
        ``pending`` (transient errors — network, timeout). Otherwise it is
        terminally ``failed``. Returns the updated job.
        """
        job = self.get(job_id)
        if job is None:
            return None
        if retry and job.attempts < job.max_attempts:
            status = JobStatus.pending
        else:
            status = JobStatus.failed
        self._conn.execute(
            "UPDATE jobs SET status = ?, error = ?, updated_at = ? WHERE id = ?",
            (status.value, error, _now(), job_id),
        )
        self._conn.commit()
        return self.get(job_id)

    def requeue_stale(self) -> int:
        """Return orphaned ``running`` jobs to ``pending`` (crash recovery).

        Called on worker startup: any job left ``running`` by a crashed worker
        is reset so it will be re-claimed. Returns the number requeued.
        """
        cur = self._conn.execute(
            "UPDATE jobs SET status = ?, updated_at = ? WHERE status = ?",
            (JobStatus.pending.value, _now(), JobStatus.running.value),
        )
        self._conn.commit()
        return cur.rowcount

    def get(self, id_or_prefix: str) -> Job | None:
        """Fetch a job by full id or by a unique id prefix.

        Ambiguous prefixes (matching more than one job) return ``None``.
        """
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM jobs WHERE id = ?", (id_or_prefix,)
        ).fetchone()
        if row is not None:
            return self._row_to_job(row)
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM jobs WHERE id LIKE ? LIMIT 2",
            (id_or_prefix + "%",),
        ).fetchall()
        if len(rows) == 1:
            return self._row_to_job(rows[0])
        return None

    def list(self, status: JobStatus | None = None) -> list[Job]:
        """List jobs (optionally filtered by status), newest first."""
        if status is None:
            rows = self._conn.execute(
                f"SELECT {_COLUMNS} FROM jobs ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"SELECT {_COLUMNS} FROM jobs WHERE status = ? "
                "ORDER BY created_at DESC",
                (status.value,),
            ).fetchall()
        return [self._row_to_job(r) for r in rows]
