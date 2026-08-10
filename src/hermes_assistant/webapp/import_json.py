"""JSON import processor for the HERMES Dashboard API (Phase 4.8).

Accepts a payload dict with one or more entity lists (risks, plans, pendenzen,
projects) and imports them into the appropriate stores.

Each entity type is imported atomically: all items in the list are validated
before any DB write, and if any item fails validation the entire entity-type
batch is aborted with no rows written.  Valid batches are committed in a single
transaction (risks) or via sequential public-API calls (plans, pendenzen).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

# Maximum import payload size: 10 MB
MAX_IMPORT_BYTES = 10 * 1024 * 1024

# Entity types recognised by this importer.
# NOTE: "reviews" is intentionally absent — review import is not implemented
# in this phase (only review export).  Payloads that include a "reviews" key
# will be rejected by validate_import_payload with a clear error message.
_VALID_ENTITY_TYPES = frozenset({"risks", "plans", "pendenzen", "projects"})

# Required fields per entity type
_REQUIRED_FIELDS: dict[str, list[str]] = {
    "risks": ["title"],
    "plans": ["plan_id", "items"],
    "pendenzen": ["title"],
    "projects": ["project_id"],
}

# Maximum items per entity list per import request
_MAX_ITEMS_PER_TYPE = 10_000


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


class ImportItemResult(BaseModel):
    """Result for a single imported item."""

    index: int
    entity_type: str
    id: str = ""
    action: str = "created"  # "created" | "updated" | "skipped"
    error: str = ""


class ImportResult(BaseModel):
    """Aggregated result of one import request."""

    ok: bool
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = Field(default_factory=list)
    items: list[ImportItemResult] = Field(default_factory=list)
    entity_counts: dict[str, int] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _gen_id() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Entity-level validators
# ---------------------------------------------------------------------------


def validate_entity(entity_type: str, obj: Any) -> list[str]:
    """Return validation errors for one entity dict. Empty list means valid."""
    errors: list[str] = []

    if not isinstance(obj, dict):
        return ["Entity must be a JSON object"]

    required = _REQUIRED_FIELDS.get(entity_type, [])
    for field in required:
        if field not in obj or obj[field] is None or obj[field] == "":
            errors.append(f"Missing required field: {field!r}")

    if entity_type == "risks":
        sev = obj.get("severity")
        if sev is not None and sev not in ("low", "medium", "high", "critical"):
            errors.append(
                "Invalid severity value; must be low/medium/high/critical"
            )
        lh = obj.get("likelihood")
        if lh is not None:
            if not isinstance(lh, int):
                errors.append("'likelihood' must be an integer")
            elif not (1 <= lh <= 5):
                errors.append("'likelihood' must be between 1 and 5")
        status = obj.get("status")
        if status is not None and status not in (
            "open", "mitigated", "accepted", "closed"
        ):
            errors.append(
                "Invalid status value; must be open/mitigated/accepted/closed"
            )

    elif entity_type == "plans":
        items = obj.get("items")
        if items is not None:
            if not isinstance(items, list):
                errors.append("'items' must be a list")
            else:
                for i, item in enumerate(items):
                    if not isinstance(item, dict):
                        errors.append(f"items[{i}] must be a JSON object")
                    elif not item.get("title"):
                        errors.append(
                            f"items[{i}] missing required field 'title'"
                        )

    elif entity_type == "pendenzen":
        priority = obj.get("priority")
        if priority is not None and priority not in (
            "low", "medium", "high", "blocker"
        ):
            errors.append(
                "Invalid priority value; must be low/medium/high/blocker"
            )

    return errors


def validate_import_payload(payload: Any) -> list[str]:
    """Validate the top-level import payload structure.

    Returns a list of error strings (empty = valid).
    """
    if not isinstance(payload, dict):
        return ["Payload must be a JSON object (dict)"]

    errors: list[str] = []

    known = {k for k in payload if k in _VALID_ENTITY_TYPES}
    if not known:
        errors.append(
            f"No recognised entity types found. "
            f"Supported: {sorted(_VALID_ENTITY_TYPES)}"
        )
        return errors

    for key in known:
        value = payload[key]
        if not isinstance(value, list):
            errors.append(
                f"{key!r} must be a list, got {type(value).__name__}"
            )
        elif len(value) > _MAX_ITEMS_PER_TYPE:
            errors.append(
                f"{key!r} has {len(value)} items; maximum is {_MAX_ITEMS_PER_TYPE}"
            )

    return errors


# ---------------------------------------------------------------------------
# Entity importers
# ---------------------------------------------------------------------------


def _import_risks(
    risks_data: list[dict[str, Any]],
    *,
    db_path: str,
    result: ImportResult,
    start_idx: int,
) -> None:
    """Import risk entities into a RiskRegistry.

    Two-pass strategy (H5 atomicity):
    1. Validate every item.  On first failure flag ``had_errors`` and continue
       collecting errors, but do not write anything.
    2. If no validation errors, INSERT all valid risks inside a single
       database transaction via the registry's connection.  A DB-level
       exception triggers rollback and is appended to result.errors.
    """
    from hermes_assistant.risks.model import Risk, RiskSeverity, RiskStatus
    from hermes_assistant.risks.registry import RiskRegistry

    _RISK_COLS = (
        "id, title, description, severity, likelihood, owner, "
        "status, confidential, created_at, updated_at"
    )

    registry = RiskRegistry(db_path)
    try:
        # --- Pass 1: validate every item; no DB writes in this phase ---
        pending: list[tuple[int, str, Risk]] = []  # (global_idx, action, risk)
        had_errors = False

        for i, raw in enumerate(risks_data):
            idx = start_idx + i
            errs = validate_entity("risks", raw)
            if errs:
                result.items.append(
                    ImportItemResult(
                        index=idx,
                        entity_type="risks",
                        action="skipped",
                        error="; ".join(errs),
                    )
                )
                result.skipped += 1
                result.errors.append(f"risks[{i}]: {'; '.join(errs)}")
                had_errors = True
                continue

            # H2: Construct the Risk defensively. An explicitly-null optional
            # field (e.g. ``"owner": null``) makes ``raw.get("owner", "")``
            # return ``None`` — defaults only apply to *absent* keys — and a
            # null severity/status/likelihood likewise breaks enum/int coercion.
            # Any such failure must be skipped like a validation error, never
            # propagate as a bare 500. Constructing inside the loop keeps the
            # atomic per-item handling intact: a construction failure sets
            # ``had_errors`` and aborts the whole entity-type batch (H5).
            try:
                risk_id = str(raw.get("id") or "") or _gen_id()
                existing = registry.get(risk_id)
                now = _now()
                sev = RiskSeverity(raw.get("severity", "medium"))
                lh = int(raw.get("likelihood", 3))
                status = RiskStatus(raw.get("status", "open"))
                risk = Risk(
                    id=risk_id,
                    title=raw["title"],
                    description=raw.get("description", ""),
                    severity=sev,
                    likelihood=lh,
                    owner=raw.get("owner", ""),
                    status=status,
                    confidential=bool(raw.get("confidential", False)),
                    created_at=existing.created_at if existing else now,
                    updated_at=now,
                )
            except Exception as exc:  # noqa: BLE001 - report, do not 500
                result.items.append(
                    ImportItemResult(
                        index=idx,
                        entity_type="risks",
                        action="skipped",
                        error=f"Invalid risk: {exc}",
                    )
                )
                result.skipped += 1
                result.errors.append(f"risks[{i}]: {exc}")
                had_errors = True
                continue

            pending.append((idx, "updated" if existing else "created", risk))

        # Atomicity: any validation failure aborts the entire entity-type batch.
        # Errors have already been collected above for reporting; no DB writes
        # will happen so the store remains consistent.
        if had_errors:
            return

        # --- Pass 2: commit all valid items in a single transaction ---
        with registry._lock:
            try:
                for idx, action, risk in pending:
                    registry._conn.execute(
                        f"INSERT OR REPLACE INTO risks ({_RISK_COLS}) VALUES"
                        " (?,?,?,?,?,?,?,?,?,?)",
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
                    result.items.append(
                        ImportItemResult(
                            index=idx,
                            entity_type="risks",
                            id=risk.id,
                            action=action,
                        )
                    )
                    if action == "updated":
                        result.updated += 1
                    else:
                        result.created += 1
                registry._conn.commit()  # single commit for all risks
            except Exception as e:
                registry._conn.rollback()
                result.errors.append(f"Failed to import risks: {e}")
    finally:
        registry.close_connection()


def _import_plans(
    plans_data: list[dict[str, Any]],
    *,
    db_path: str,
    result: ImportResult,
    start_idx: int,
) -> None:
    """Import plan versions into a PlanEditor.

    Two-pass strategy (H5 atomicity):
    1. Validate every item.  Any failure flags the batch; no writes occur.
    2. If all items are valid, write them via the PlanEditor public API.
    """
    from hermes_assistant.plans.editor import PlanEditor
    from hermes_assistant.plans.model import PlanItem

    editor = PlanEditor(db_path)
    try:
        # --- Pass 1: validate every item; no DB writes in this phase ---
        pending: list[tuple[int, str, str, list[PlanItem], bool]] = []
        had_errors = False

        for i, raw in enumerate(plans_data):
            idx = start_idx + i
            errs = validate_entity("plans", raw)
            if errs:
                result.items.append(
                    ImportItemResult(
                        index=idx,
                        entity_type="plans",
                        action="skipped",
                        error="; ".join(errs),
                    )
                )
                result.skipped += 1
                result.errors.append(f"plans[{i}]: {'; '.join(errs)}")
                had_errors = True
                continue

            plan_id = str(raw["plan_id"])
            author = str(raw.get("author", "import"))
            items_raw = raw.get("items", [])
            items = [
                PlanItem(
                    id=str(item.get("id") or _gen_id()),
                    title=str(item["title"]),
                    phase=str(item.get("phase", "")),
                    assignee=str(item.get("assignee", "")),
                    role=str(item.get("role", "")),
                    status=item.get("status", "open"),
                    order=int(item.get("order", 0)),
                )
                for item in items_raw
            ]
            existing = editor.get(plan_id)
            pending.append((idx, plan_id, author, items, existing is not None))

        # Atomicity: any validation failure aborts the entire entity-type batch.
        if had_errors:
            return

        # --- Pass 2: write all valid plans via public API ---
        for idx, plan_id, author, items, is_update in pending:
            if is_update:
                editor.update(plan_id, items, author=author)
                action = "updated"
                result.updated += 1
            else:
                editor.create(plan_id, items, author=author)
                action = "created"
                result.created += 1
            result.items.append(
                ImportItemResult(
                    index=idx, entity_type="plans", id=plan_id, action=action,
                )
            )
    finally:
        editor.close()


def _import_pendenzen(
    pend_data: list[dict[str, Any]],
    *,
    db_path: str,
    result: ImportResult,
    start_idx: int,
) -> None:
    """Import pendenzen into the TaskStore.

    Two-pass strategy (H5 atomicity):
    1. Validate every item.  Any failure flags the batch; no writes occur.
    2. If all items are valid, write them via the TaskStore public API.

    Idempotency (M2): ``external_ref`` (set by the Copilot adapter) is used as
    the primary deduplication key.  If absent, falls back to ``id``.  When a
    matching row is found, the record is updated in-place rather than creating
    a duplicate.
    """
    from hermes_assistant.tasks.pendenzen import Pendenz, PendenzSource
    from hermes_assistant.tasks.store import TaskStore

    store = TaskStore(db_path)
    try:
        # --- Pass 1: validate every item; no DB writes in this phase ---
        # Tuple: (global_idx, external_ref | None, raw_id | None, raw_dict)
        pending: list[tuple[int, str | None, str | None, dict[str, Any]]] = []
        had_errors = False

        for i, raw in enumerate(pend_data):
            idx = start_idx + i
            errs = validate_entity("pendenzen", raw)
            if errs:
                result.items.append(
                    ImportItemResult(
                        index=idx,
                        entity_type="pendenzen",
                        action="skipped",
                        error="; ".join(errs),
                    )
                )
                result.skipped += 1
                result.errors.append(f"pendenzen[{i}]: {'; '.join(errs)}")
                had_errors = True
                continue

            # M2: prefer external_ref; fall back to id; both may be absent.
            external_ref = str(raw.get("external_ref") or "").strip() or None
            raw_id = str(raw.get("id") or "").strip() or None
            pending.append((idx, external_ref, raw_id, raw))

        # Atomicity: any validation failure aborts the entire entity-type batch.
        if had_errors:
            return

        # --- Pass 2: write all valid pendenzen via public API ---
        for idx, external_ref, raw_id, raw in pending:
            source_str = raw.get("source", "manual")
            try:
                source = PendenzSource(source_str)
            except ValueError:
                source = PendenzSource.manual

            # M2: look up by external_ref first (Copilot path), then by id
            # (legacy path).  Only generate a fresh ID when truly absent.
            existing = None
            if external_ref:
                existing = store.find_by_external_ref(external_ref)
            elif raw_id:
                existing = store.get(raw_id)

            if existing is not None:
                store.update(existing.id, title=raw["title"])
                result.items.append(
                    ImportItemResult(
                        index=idx,
                        entity_type="pendenzen",
                        id=existing.id,
                        action="updated",
                    )
                )
                result.updated += 1
            else:
                p = Pendenz(
                    id=raw_id or "",
                    title=raw["title"],
                    description=raw.get("description", ""),
                    owner=raw.get("owner"),
                    priority=raw.get("priority", "medium"),
                    source=source,
                    source_ref=raw.get("source_ref"),
                    external_ref=external_ref,
                )
                new_id = store.create(p)
                result.items.append(
                    ImportItemResult(
                        index=idx,
                        entity_type="pendenzen",
                        id=new_id,
                        action="created",
                    )
                )
                result.created += 1
    finally:
        store.close()


def _import_projects(
    projects_data: list[dict[str, Any]],
    *,
    projects_root: str,
    result: ImportResult,
    start_idx: int,
) -> None:
    """Create project directories for stub projects.

    Two-pass strategy (H5 atomicity):
    1. Validate every item.  Any failure flags the batch; no directories are
       created.
    2. If all items are valid, create the directories.
    """
    from pathlib import Path

    root = Path(projects_root)

    # --- Pass 1: validate every item; no filesystem writes in this phase ---
    pending: list[tuple[int, str]] = []
    had_errors = False

    for i, raw in enumerate(projects_data):
        idx = start_idx + i
        errs = validate_entity("projects", raw)
        if errs:
            result.items.append(
                ImportItemResult(
                    index=idx,
                    entity_type="projects",
                    action="skipped",
                    error="; ".join(errs),
                )
            )
            result.skipped += 1
            result.errors.append(f"projects[{i}]: {'; '.join(errs)}")
            had_errors = True
            continue

        pending.append((idx, str(raw["project_id"])))

    # Atomicity: any validation failure aborts the entire entity-type batch.
    if had_errors:
        return

    # --- Pass 2: create directories for all valid projects ---
    for idx, project_id in pending:
        proj_dir = root / project_id
        existed = proj_dir.exists()
        proj_dir.mkdir(parents=True, exist_ok=True)
        action = "updated" if existed else "created"
        result.items.append(
            ImportItemResult(
                index=idx, entity_type="projects", id=project_id, action=action,
            )
        )
        if existed:
            result.updated += 1
        else:
            result.created += 1


# ---------------------------------------------------------------------------
# Public import entry point
# ---------------------------------------------------------------------------


def import_payload(
    payload: dict[str, Any],
    *,
    risks_db: str = ":memory:",
    plans_db: str = ":memory:",
    tasks_db: str = ":memory:",
    projects_root: str | None = None,
) -> ImportResult:
    """Execute a partial import for all entity types present in *payload*.

    Each entity type is imported all-or-nothing per entity type: all items in
    the list are validated before any DB write, and if any item fails
    validation the entire entity-type batch is aborted with no rows written
    (all risks commit or all fail; same for plans, pendenzen, and projects).
    Valid batches are committed in a single transaction.

    Size-limit precedence note: ``_MAX_ITEMS_PER_TYPE`` (10 000 items) is
    stricter than the 10 MB byte limit on an *item-count* basis.  If a
    payload has fewer than 10 000 items but the raw JSON exceeds 10 MB, the
    byte limit (enforced at the server.py level before this function is
    called) takes precedence and the request is rejected before import runs.

    Returns a full :class:`ImportResult`.

    Parameters
    ----------
    payload:       Already-parsed dict (validated by validate_import_payload).
    risks_db:      SQLite path for RiskRegistry (":memory:" for tests).
    plans_db:      SQLite path for PlanEditor (":memory:" for tests).
    tasks_db:      SQLite path for TaskStore (":memory:" for tests).
    projects_root: Directory root for project stubs.
    """
    import tempfile

    _proj_root = projects_root or str(tempfile.mkdtemp(prefix="hermes-projects-"))
    result = ImportResult(ok=True)
    counts: dict[str, int] = {}
    idx = 0

    if "risks" in payload:
        lst = payload["risks"] or []
        counts["risks"] = len(lst)
        _import_risks(lst, db_path=risks_db, result=result, start_idx=idx)
        idx += len(lst)

    if "plans" in payload:
        lst = payload["plans"] or []
        counts["plans"] = len(lst)
        _import_plans(lst, db_path=plans_db, result=result, start_idx=idx)
        idx += len(lst)

    if "pendenzen" in payload:
        lst = payload["pendenzen"] or []
        counts["pendenzen"] = len(lst)
        _import_pendenzen(lst, db_path=tasks_db, result=result, start_idx=idx)
        idx += len(lst)

    if "projects" in payload:
        lst = payload["projects"] or []
        counts["projects"] = len(lst)
        _import_projects(
            lst, projects_root=_proj_root, result=result, start_idx=idx
        )
        idx += len(lst)

    result.entity_counts = counts
    total_attempted = result.created + result.updated + result.skipped
    result.ok = total_attempted == 0 or (result.created + result.updated) > 0
    return result
