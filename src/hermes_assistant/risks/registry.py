"""SQLite-backed risk registry for HERMES project risk tracking.

Risks are persisted in a single WAL-mode SQLite file. The registry supports
full CRUD, keyword-based auto-extraction, filtering by status/severity/owner,
multi-column sorting, confidentiality guards, and concurrent access via
SQLite's built-in serialisation.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from hermes_assistant.risks.model import Risk, RiskSeverity, RiskStatus

_COLUMNS = (
    "id, title, description, severity, likelihood, owner, "
    "status, confidential, created_at, updated_at"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS risks (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    severity     TEXT NOT NULL DEFAULT 'medium',
    likelihood   INTEGER NOT NULL DEFAULT 3,
    owner        TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'open',
    confidential INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_risks_status   ON risks (status);
CREATE INDEX IF NOT EXISTS idx_risks_severity ON risks (severity);
"""

_SEVERITY_ORDER = {
    RiskSeverity.low: 1,
    RiskSeverity.medium: 2,
    RiskSeverity.high: 3,
    RiskSeverity.critical: 4,
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


class RiskNotFoundError(KeyError):
    """Raised when an operation targets a non-existent risk id."""


class RiskRegistry:
    """Persistent registry of project risks.

    ``":memory:"`` is accepted as db_path for isolated in-process tests.
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

    def close_connection(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _row_to_risk(self, row: sqlite3.Row) -> Risk:
        return Risk(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            severity=RiskSeverity(row["severity"]),
            likelihood=row["likelihood"],
            owner=row["owner"],
            status=RiskStatus(row["status"]),
            confidential=bool(row["confidential"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(
        self,
        title: str,
        *,
        description: str = "",
        severity: RiskSeverity = RiskSeverity.medium,
        likelihood: int = 3,
        owner: str = "",
        confidential: bool = False,
    ) -> Risk:
        """Insert a new risk and return it."""
        risk = Risk(
            title=title,
            description=description,
            severity=severity,
            likelihood=likelihood,
            owner=owner,
            confidential=confidential,
        )
        self._conn.execute(
            f"INSERT INTO risks ({_COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                risk.id,
                risk.title,
                risk.description,
                risk.severity.value,
                risk.likelihood,
                risk.owner,
                risk.status.value,
                int(risk.confidential),
                risk.created_at,
                risk.updated_at,
            ),
        )
        self._conn.commit()
        return risk

    def get(self, risk_id: str) -> Risk | None:
        """Fetch a risk by id; returns None if not found."""
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM risks WHERE id = ?", (risk_id,)
        ).fetchone()
        return self._row_to_risk(row) if row else None

    def update(self, risk_id: str, **kwargs: object) -> Risk:
        """Update one or more fields of a risk.

        Raises ``RiskNotFoundError`` if the id does not exist.
        Allowed kwargs: title, description, severity, likelihood, owner,
        status, confidential.
        """
        risk = self.get(risk_id)
        if risk is None:
            raise RiskNotFoundError(risk_id)
        allowed = {
            "title", "description", "severity", "likelihood",
            "owner", "status", "confidential",
        }
        for k, v in kwargs.items():
            if k not in allowed:
                raise ValueError(f"Unknown field: {k!r}")
            setattr(risk, k, v)
        risk.updated_at = _now()
        self._conn.execute(
            "UPDATE risks SET title=?, description=?, severity=?, likelihood=?, "
            "owner=?, status=?, confidential=?, updated_at=? WHERE id=?",
            (
                risk.title,
                risk.description,
                risk.severity.value,
                risk.likelihood,
                risk.owner,
                risk.status.value,
                int(risk.confidential),
                risk.updated_at,
                risk_id,
            ),
        )
        self._conn.commit()
        return risk

    def delete(self, risk_id: str) -> bool:
        """Remove a risk; returns True if deleted, False if not found."""
        cur = self._conn.execute("DELETE FROM risks WHERE id = ?", (risk_id,))
        self._conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------

    def accept(self, risk_id: str) -> Risk:
        """Mark a risk as accepted (owner acknowledges it, no mitigation)."""
        return self.update(risk_id, status=RiskStatus.accepted)

    def mitigate(self, risk_id: str) -> Risk:
        """Mark a risk as mitigated (countermeasure applied)."""
        return self.update(risk_id, status=RiskStatus.mitigated)

    def close(self, risk_id: str | None = None) -> Risk | None:
        """Mark a risk as closed, or close the connection if no id is given.

        Called with a ``risk_id`` -> marks that risk as closed (no longer
        applicable) and returns the updated :class:`Risk`.
        Called with no arguments -> closes the underlying SQLite connection
        (equivalent to :meth:`close_connection`) and returns ``None``.
        """
        if risk_id is None:
            self.close_connection()
            return None
        return self.update(risk_id, status=RiskStatus.closed)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def list(
        self,
        *,
        status: RiskStatus | None = None,
        severity: RiskSeverity | None = None,
        owner: str | None = None,
        sort_by: str = "created_at",
        descending: bool = True,
    ) -> list[Risk]:
        """Return risks matching the given filters, ordered as requested.

        ``sort_by`` accepts any column name; ``"severity"`` applies a
        semantic ordering (low < medium < high < critical) rather than
        lexicographic.
        """
        where_clauses: list[str] = []
        params: list[object] = []
        if status is not None:
            where_clauses.append("status = ?")
            params.append(status.value)
        if severity is not None:
            where_clauses.append("severity = ?")
            params.append(severity.value)
        if owner is not None:
            where_clauses.append("owner = ?")
            params.append(owner)
        where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        # Severity needs client-side sort; all others delegate to SQLite.
        if sort_by == "severity":
            rows = self._conn.execute(
                f"SELECT {_COLUMNS} FROM risks {where}", params
            ).fetchall()
            risks = [self._row_to_risk(r) for r in rows]
            return sorted(
                risks,
                key=lambda r: _SEVERITY_ORDER[r.severity],
                reverse=descending,
            )
        order = f"ORDER BY {sort_by} {'DESC' if descending else 'ASC'}"
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM risks {where} {order}", params
        ).fetchall()
        return [self._row_to_risk(r) for r in rows]

    # ------------------------------------------------------------------
    # Auto-creation
    # ------------------------------------------------------------------

    def auto_create(self, text: str) -> Risk:
        """Parse free text and create a risk entry.

        Heuristic: first non-empty line → title; remainder → description;
        severity detected from keywords (critical/high/medium/low).
        """
        lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
        title = lines[0][:200] if lines else "Unnamed risk"
        description = " ".join(lines[1:]) if len(lines) > 1 else ""
        text_lower = text.lower()
        if any(w in text_lower for w in ("critical", "blocker", "catastrophic", "severe")):
            severity = RiskSeverity.critical
        elif any(w in text_lower for w in ("high", "serious", "major", "significant")):
            severity = RiskSeverity.high
        elif any(w in text_lower for w in ("low", "minor", "negligible", "trivial")):
            severity = RiskSeverity.low
        else:
            severity = RiskSeverity.medium
        return self.create(title, description=description, severity=severity)

    # ------------------------------------------------------------------
    # Confidentiality
    # ------------------------------------------------------------------

    def export_public(self) -> list[Risk]:
        """Return only non-confidential risks (safe for external sharing)."""
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM risks WHERE confidential = 0 "
            "ORDER BY created_at DESC"
        ).fetchall()
        return [self._row_to_risk(r) for r in rows]
