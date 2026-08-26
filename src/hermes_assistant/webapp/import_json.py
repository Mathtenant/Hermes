"""JSON import processor for the HERMES Dashboard API (Phase 4.8).

Accepts a payload dict with one or more entity lists (risks, plans, pendenzen,
projects) and imports them into the appropriate stores.

Each entity type is imported atomically: all items in the list are validated
before any DB write, and if any item fails validation the entire entity-type
batch is aborted with no rows written.  Valid batches are committed in a single
transaction (risks) or via sequential public-API calls (plans, pendenzen).
"""
from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime
from typing import Any

from pydantic import BaseModel, Field

# Schedule due dates must be plain calendar dates — the Timeline screen
# compares them as strings against today, so any other shape sorts wrongly.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Maximum import payload size: 10 MB
MAX_IMPORT_BYTES = 10 * 1024 * 1024

# Entity types recognised by this importer.
# NOTE: "reviews" is intentionally absent — review import is not implemented
# in this phase (only review export).  Payloads that include a "reviews" key
# will be rejected by validate_import_payload with a clear error message.
_VALID_ENTITY_TYPES = frozenset(
    {"risks", "plans", "pendenzen", "projects", "tasks", "schedule"}
)

# Required fields per entity type
_REQUIRED_FIELDS: dict[str, list[str]] = {
    "risks": ["title"],
    "plans": ["plan_id", "items"],
    "pendenzen": ["title"],
    "projects": ["project_id"],
    # "tasks" feeds the TaskStore tree that the WBS and Kanban screens render.
    # (The older "plans" type writes to plans.db, which no dashboard screen
    # reads — so a work breakdown must arrive as "tasks" to become visible.)
    "tasks": ["title"],
    # "schedule" writes <projects_root>/<project_id>/schedule.json, the only
    # source the Timeline screen reads.
    "schedule": ["project_id", "items"],
}

# Enum domains for the task tree, mirroring hermes_assistant.tasks.model.Task.
_TASK_STATUSES = ("open", "closed", "blocked")
_TASK_NODE_KINDS = (
    "milestone", "deliverable", "task", "decision", "pendenz", "assumption",
)
_SCHEDULE_ITEM_KINDS = ("milestone", "deadline", "task")

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
# Import-time safety
#
# Imported content is machine-generated from documents nobody vetted, so it is
# the least trustworthy input the system takes. Two classes of damage have to
# be stopped at this boundary, because neither is recoverable downstream.
# ---------------------------------------------------------------------------

# Free-text fields that end up rendered on the dashboard, per entity type.
_TEXT_FIELDS: dict[str, tuple[str, ...]] = {
    "risks": ("title", "description", "owner"),
    "pendenzen": ("title", "description", "owner", "source_ref"),
    "tasks": ("title", "description", "owner"),
    "plans": ("title",),
    "schedule": ("title", "note"),
}


def _guard_patterns() -> tuple[Any, Any]:
    """Return the (email, filesystem-path) regexes the response guard uses.

    Imported lazily and taken from the guard itself rather than re-declared
    here: if the two ever drifted, content could pass import and then break
    every dashboard response — the exact failure this is meant to prevent.
    """
    from hermes_assistant.webapp.server import _EMAIL_RE, _FS_RE

    return _EMAIL_RE, _FS_RE


def _redact_unsafe_text(value: str) -> tuple[str, list[str]]:
    """Strip content that would later trip the confidentiality guard.

    ``/api/dashboard`` runs every response through ``_validate_safe_json`` and
    returns HTTP 500 if it finds an email address or an absolute filesystem
    path. Because imported rows are stored verbatim, a single meeting-derived
    pendenz titled "Klärung mit hans.muster@example.com" would make the whole
    dashboard 500 on every request, permanently, until somebody edited the
    database by hand.

    Redacting is deliberate rather than rejecting the row: an export drawn
    from meeting minutes will routinely mention people by address, and failing
    the whole batch would leave the user hand-editing JSON. The substitution
    is always reported back so nothing changes silently.
    """
    email_re, fs_re = _guard_patterns()
    notes: list[str] = []
    cleaned, n_mail = email_re.subn("[E-Mail entfernt]", value)
    if n_mail:
        notes.append(f"{n_mail} E-Mail-Adresse(n)")
    cleaned, n_path = fs_re.subn("[Pfad entfernt]", cleaned)
    if n_path:
        notes.append(f"{n_path} Dateipfad(e)")
    return cleaned, notes


def _sanitise_entity(entity_type: str, raw: dict[str, Any]) -> list[str]:
    """Redact guard-tripping text in place; return human-readable notes."""
    notes: list[str] = []
    for field in _TEXT_FIELDS.get(entity_type, ()):
        value = raw.get(field)
        if isinstance(value, str) and value:
            cleaned, found = _redact_unsafe_text(value)
            if found:
                raw[field] = cleaned
                notes.append(f"{field}: {', '.join(found)} entfernt")
    return notes


def _strip_trailing_commas(text: str) -> str:
    """Remove ``,`` that sits directly before a closing brace or bracket.

    Scanned character by character with string/escape awareness rather than by
    regex: a naive pattern would also rewrite a comma inside a value such as
    ``"Abnahme, }"``, silently corrupting the user's data to fix a syntax
    error. Only commas in structural position are touched.
    """
    out: list[str] = []
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            continue
        if ch == ",":
            rest = text[i + 1 :]
            stripped = rest.lstrip()
            if stripped[:1] in ("}", "]"):
                continue  # structural trailing comma — drop it
        out.append(ch)
    return "".join(out)


def loads_forgiving(raw: str | bytes) -> tuple[Any, list[str]]:
    """Parse JSON, tolerating the wrappers language models routinely add.

    The prompts forbid code fences and prose, but models emit them anyway, and
    a bare ``Expecting value: line 1 column 1`` tells the user nothing they can
    act on. Strict parsing is tried first, so a well-formed export takes the
    fast path and is never rewritten.

    Repairs are limited to material *outside* the JSON document plus
    structural trailing commas, and every one is reported so the user can see
    that their export was not clean.

    Returns ``(payload, repairs)``. Raises ``json.JSONDecodeError`` if the text
    cannot be salvaged.
    """
    import json

    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    repairs: list[str] = []

    try:
        return json.loads(text), repairs
    except json.JSONDecodeError:
        pass

    candidate = text.lstrip("﻿").strip()
    if candidate != text.strip():
        repairs.append("Byte-Order-Mark entfernt")

    # ```json … ``` — by far the most common deviation.
    fence = re.search(r"```[a-zA-Z]*\s*(.*?)```", candidate, re.DOTALL)
    if fence:
        candidate = fence.group(1).strip()
        repairs.append("Markdown-Code-Fence entfernt")

    # "Here is the JSON you asked for: { … }" — keep the outermost object.
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start > 0 or (end != -1 and end < len(candidate) - 1):
        if start != -1 and end > start:
            candidate = candidate[start : end + 1]
            repairs.append("Text vor/nach dem JSON entfernt")

    try:
        return json.loads(candidate), repairs
    except json.JSONDecodeError:
        pass

    without_commas = _strip_trailing_commas(candidate)
    if without_commas != candidate:
        payload = json.loads(without_commas)  # may raise — nothing left to try
        repairs.append("Nachgestellte Kommas entfernt")
        return payload, repairs

    # Nothing worked: re-raise the error for the best candidate we produced,
    # so the reported position refers to the text we actually tried to parse.
    return json.loads(candidate), repairs


# A project id becomes a directory name under projects_root. Anything with a
# separator, a parent reference, or a drive letter can escape that root — a
# "project_ref" of "proj/../../x" wrote schedule.json two levels above it.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


def _is_safe_path_segment(value: str) -> bool:
    """True if *value* is safe to use as a single directory name."""
    return bool(_SAFE_ID_RE.match(value)) and value not in (".", "..")


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

    elif entity_type == "tasks":
        status = obj.get("status")
        if status is not None and status not in _TASK_STATUSES:
            errors.append(
                f"Invalid status value; must be {'/'.join(_TASK_STATUSES)}"
            )
        node_kind = obj.get("node_kind")
        if node_kind is not None and node_kind not in _TASK_NODE_KINDS:
            errors.append(
                f"Invalid node_kind value; must be {'/'.join(_TASK_NODE_KINDS)}"
            )

    elif entity_type == "schedule":
        project_id = obj.get("project_id")
        if project_id is not None and not _is_safe_path_segment(str(project_id)):
            errors.append(
                f"Invalid project_id {project_id!r}: must be a single safe "
                "directory name (letters, digits, . _ -)"
            )
        items = obj.get("items")
        if items is not None:
            if not isinstance(items, list):
                errors.append("'items' must be a list")
            else:
                for i, item in enumerate(items):
                    if not isinstance(item, dict):
                        errors.append(f"items[{i}] must be a JSON object")
                        continue
                    if not item.get("title"):
                        errors.append(f"items[{i}] missing required field 'title'")
                    due = item.get("due")
                    if not due:
                        errors.append(f"items[{i}] missing required field 'due'")
                    elif not _DATE_RE.match(str(due)):
                        errors.append(
                            f"items[{i}] 'due' must be YYYY-MM-DD, got {due!r}"
                        )
                    else:
                        # Shape alone is not enough: "2026-02-30" matches the
                        # pattern but is not a real date, and would raise
                        # deep inside the writer as an uncaught HTTP 500.
                        try:
                            date.fromisoformat(str(due))
                        except ValueError:
                            errors.append(
                                f"items[{i}] 'due' is not a valid calendar "
                                f"date: {due!r}"
                            )
                    kind = item.get("kind")
                    if kind is not None and kind not in _SCHEDULE_ITEM_KINDS:
                        errors.append(
                            f"items[{i}] invalid kind; must be "
                            f"{'/'.join(_SCHEDULE_ITEM_KINDS)}"
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
        "status, confidential, created_at, updated_at, accepted_at, external_ref"
    )

    registry = RiskRegistry(db_path)
    try:
        # --- Pass 1: validate every item; no DB writes in this phase ---
        pending: list[tuple[int, str, Risk]] = []  # (global_idx, action, risk)
        had_errors = False

        for i, raw in enumerate(risks_data):
            idx = start_idx + i
            if isinstance(raw, dict):
                for note in _sanitise_entity("risks", raw):
                    result.errors.append(f"risks[{i}]: {note}")
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
                # M2: prefer external_ref (Copilot dedup key); fall back to id
                # (legacy path) so pre-M2 payloads keep working unchanged.
                external_ref = str(raw.get("external_ref") or "").strip() or None
                existing = None
                if external_ref:
                    existing = registry.get_by_external_ref(external_ref)
                if existing is None:
                    raw_id = str(raw.get("id") or "") or ""
                    existing = registry.get(raw_id) if raw_id else None
                risk_id = existing.id if existing else (str(raw.get("id") or "") or _gen_id())
                now = _now()
                sev = RiskSeverity(raw.get("severity", "medium"))
                lh = int(raw.get("likelihood", 3))
                # D5: a closed risk is terminal. Re-importing a risk that was
                # already closed must not resurrect it, regardless of what
                # status the incoming payload carries.
                if existing is not None and existing.status == RiskStatus.closed:
                    status = existing.status
                else:
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
                    external_ref=external_ref,
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
                        " (?,?,?,?,?,?,?,?,?,?,?,?)",
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
                            risk.accepted_at,
                            risk.external_ref,
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
            if isinstance(raw, dict):
                for note in _sanitise_entity("pendenzen", raw):
                    result.errors.append(f"pendenzen[{i}]: {note}")
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


def _topo_order_tasks(
    tasks_data: list[dict[str, Any]],
    known_refs: frozenset[str] = frozenset(),
) -> tuple[list[tuple[int, dict[str, Any]]], list[str]]:
    """Order tasks parents-first, so a child is never created before its parent.

    ``TaskStore.create`` computes ``wbs_number`` from the parent and registers
    the child in the parent's ``children_ids``; ``update`` does not keep the
    indexed ``parent_id`` column in sync. Creating in dependency order is
    therefore the only way to build a correct tree in one pass.

    ``known_refs`` holds external_refs that already exist in the store. A
    parent_ref matching one of those is legitimate — it is how an incremental
    or subtree export attaches to a tree imported earlier — so it is treated
    as a satisfied dependency rather than a dangling reference.

    Returns ``(ordered, errors)``. ``ordered`` holds ``(original_index, raw)``
    pairs. A cycle, a duplicate external_ref, or a ``parent_ref`` naming a node
    that is neither in this payload nor already stored is reported as an error
    rather than silently flattening the tree — a silently flattened WBS looks
    plausible but is wrong.

    The walk is iterative on purpose. A recursive version overflowed the stack
    at roughly 2 000 nodes when the payload listed children before parents,
    which the prompt explicitly permits, turning a large but legal export into
    an HTTP 500.
    """
    ordered: list[tuple[int, dict[str, Any]]] = []
    errors: list[str] = []

    by_ref: dict[str, int] = {}
    for i, raw in enumerate(tasks_data):
        ref = str(raw.get("external_ref") or "").strip()
        if not ref:
            continue
        if ref in by_ref:
            # Deterministic slugs are derived from titles and truncated to 60
            # characters, so two long titles can collide. Overwriting would
            # drop a row with no error at all.
            errors.append(
                f"tasks[{i}]: duplicate external_ref {ref!r} "
                f"(also used by tasks[{by_ref[ref]}])"
            )
            continue
        by_ref[ref] = i

    # 0 = unvisited, 1 = on the current path (cycle marker), 2 = emitted
    state: dict[int, int] = {}

    for start in range(len(tasks_data)):
        if state.get(start, 0) == 2:
            continue
        # Explicit stack of (index, children_expanded?) frames.
        stack: list[tuple[int, bool]] = [(start, False)]
        path: list[str] = []
        while stack:
            i, expanded = stack.pop()
            raw = tasks_data[i]
            own_ref = str(raw.get("external_ref") or "").strip()

            if expanded:
                state[i] = 2
                ordered.append((i, raw))
                if path and path[-1] == (own_ref or f"#{i}"):
                    path.pop()
                continue

            mark = state.get(i, 0)
            if mark == 2:
                continue
            if mark == 1:
                errors.append(
                    f"tasks[{i}]: cycle in parent_ref chain "
                    f"({' -> '.join([*path, own_ref or f'#{i}'])})"
                )
                stack.clear()
                break

            state[i] = 1
            path.append(own_ref or f"#{i}")
            stack.append((i, True))

            parent_ref = str(raw.get("parent_ref") or "").strip()
            if not parent_ref:
                continue
            parent_idx = by_ref.get(parent_ref)
            if parent_idx is None:
                if parent_ref in known_refs:
                    continue  # already in the store — a valid attachment point
                errors.append(
                    f"tasks[{i}]: parent_ref {parent_ref!r} is neither an "
                    "external_ref in this payload nor an already-imported task"
                )
                stack.clear()
                break
            if state.get(parent_idx, 0) != 2:
                stack.append((parent_idx, False))

    return ordered, errors


def _import_tasks(
    tasks_data: list[dict[str, Any]],
    *,
    db_path: str,
    result: ImportResult,
    start_idx: int,
) -> None:
    """Import a work-breakdown tree into the TaskStore.

    This is what the WBS and Kanban screens render: both are views over the
    same task tree (Kanban groups it by ``status``, WBS nests it by
    ``parent_id``), which is why one payload feeds both.

    Two-pass strategy, matching the other importers: validate everything —
    including tree structure — before any write, so a broken payload never
    leaves a half-built tree behind.

    Idempotency: ``external_ref`` is the dedup key. An existing task is
    updated in place; its parent is left alone, because re-parenting cannot be
    done safely through the public API.
    """
    from hermes_assistant.tasks.model import Task
    from hermes_assistant.tasks.store import TaskStore

    store = TaskStore(db_path)
    try:
        # --- Pass 1: per-item validation ---
        had_errors = False
        for i, raw in enumerate(tasks_data):
            idx = start_idx + i
            if isinstance(raw, dict):
                for note in _sanitise_entity("tasks", raw):
                    result.errors.append(f"tasks[{i}]: {note}")
            errs = validate_entity("tasks", raw)
            if errs:
                result.items.append(
                    ImportItemResult(
                        index=idx,
                        entity_type="tasks",
                        action="skipped",
                        error="; ".join(errs),
                    )
                )
                result.skipped += 1
                result.errors.append(f"tasks[{i}]: {'; '.join(errs)}")
                had_errors = True

        # --- Pass 1b: tree structure (cycles, duplicates, dangling refs) ---
        # Refs already in the store count as valid attachment points, so an
        # incremental export can hang new work off an existing tree.
        known_refs = frozenset(
            ref
            for ref in (
                str(raw.get("parent_ref") or "").strip() for raw in tasks_data
            )
            if ref and store.find_by_external_ref(ref) is not None
        )
        ordered, tree_errors = _topo_order_tasks(tasks_data, known_refs)
        if tree_errors:
            for msg in tree_errors:
                result.errors.append(msg)
            result.skipped += len(tree_errors)
            had_errors = True

        if had_errors:
            return

        # --- Pass 2: create parents before children ---
        ref_to_id: dict[str, str] = {}
        for i, raw in ordered:
            idx = start_idx + i
            external_ref = str(raw.get("external_ref") or "").strip() or None
            parent_ref = str(raw.get("parent_ref") or "").strip() or None
            parent_id = None
            if parent_ref:
                parent_id = ref_to_id.get(parent_ref)
                if parent_id is None:
                    # Validated above as a known ref: attach to the stored tree.
                    stored_parent = store.find_by_external_ref(parent_ref)
                    if stored_parent is not None:
                        parent_id = stored_parent.id

            existing = (
                store.find_by_external_ref(external_ref) if external_ref else None
            )
            if existing is not None:
                store.update(
                    existing.id,
                    title=raw["title"],
                    status=raw.get("status", existing.status),
                    owner=raw.get("owner", existing.owner),
                    node_kind=raw.get("node_kind", existing.node_kind),
                )
                # Re-parenting has to go through set_parent(): update() writes
                # the blob but syncs only the status column, so the indexed
                # parent_id — the one the tree is read from — would keep
                # pointing at the old parent. Without this, correcting a
                # structure in Copilot and re-importing reported "n updated"
                # while the WBS on screen never moved.
                if existing.parent_id != parent_id:
                    try:
                        store.set_parent(existing.id, parent_id)
                    except (KeyError, ValueError) as exc:
                        result.errors.append(
                            f"tasks[{i}]: could not re-parent {raw['title']!r}: {exc}"
                        )
                if external_ref:
                    ref_to_id[external_ref] = existing.id
                result.items.append(
                    ImportItemResult(
                        index=idx,
                        entity_type="tasks",
                        id=existing.id,
                        action="updated",
                    )
                )
                result.updated += 1
                continue

            task = Task(
                id="",
                title=raw["title"],
                description=raw.get("description", ""),
                owner=raw.get("owner"),
                status=raw.get("status", "open"),
                node_kind=raw.get("node_kind", "task"),
                parent_id=parent_id,
                external_ref=external_ref,
            )
            new_id = store.create(task)
            if external_ref:
                ref_to_id[external_ref] = new_id
            result.items.append(
                ImportItemResult(
                    index=idx, entity_type="tasks", id=new_id, action="created"
                )
            )
            result.created += 1
    finally:
        store.close()


def _import_schedule(
    schedule_data: list[dict[str, Any]],
    *,
    projects_root: str,
    result: ImportResult,
    start_idx: int,
) -> None:
    """Write ``<projects_root>/<project_id>/schedule.json`` per project.

    That file is the only source the Timeline screen reads, so a schedule has
    to land on disk as a whole document rather than in a database. Each entry
    replaces the project's schedule outright — a partial merge would leave
    stale dates that look current.
    """
    from pathlib import Path

    from hermes_assistant.scheduling.model import ItemKind, ScheduledItem
    from hermes_assistant.scheduling.model import Schedule as _Schedule

    root = Path(projects_root)

    # --- Pass 1: validate every schedule before writing any file ---
    had_errors = False
    for i, raw in enumerate(schedule_data):
        idx = start_idx + i
        if isinstance(raw, dict):
            for item in raw.get("items") or []:
                if isinstance(item, dict):
                    for note in _sanitise_entity("schedule", item):
                        result.errors.append(f"schedule[{i}]: {note}")
        errs = validate_entity("schedule", raw)
        if errs:
            result.items.append(
                ImportItemResult(
                    index=idx,
                    entity_type="schedule",
                    action="skipped",
                    error="; ".join(errs),
                )
            )
            result.skipped += 1
            result.errors.append(f"schedule[{i}]: {'; '.join(errs)}")
            had_errors = True

    if had_errors:
        return

    # --- Pass 2: write ---
    for i, raw in enumerate(schedule_data):
        idx = start_idx + i
        project_id = str(raw["project_id"])
        label = str(raw.get("project_label") or project_id)
        items: list[ScheduledItem] = []
        for n, item in enumerate(raw.get("items") or []):
            item_id = str(item.get("item_id") or item.get("external_ref") or f"item-{n}")
            items.append(
                ScheduledItem(
                    uid=f"hermes-{project_id}-{item_id}@local",
                    project_id=project_id,
                    project_label=label,
                    item_id=item_id,
                    title=str(item["title"]),
                    kind=ItemKind(str(item.get("kind", "milestone"))),
                    due=date.fromisoformat(str(item["due"])),
                    note=item.get("note"),
                )
            )
        schedule = _Schedule(
            project_id=project_id,
            generated_at=datetime.now(UTC),
            items=items,
        )
        proj_dir = root / project_id
        proj_dir.mkdir(parents=True, exist_ok=True)
        existed = (proj_dir / "schedule.json").is_file()
        (proj_dir / "schedule.json").write_text(
            schedule.model_dump_json(indent=2), encoding="utf-8"
        )
        result.items.append(
            ImportItemResult(
                index=idx,
                entity_type="schedule",
                id=project_id,
                action="updated" if existed else "created",
            )
        )
        if existed:
            result.updated += 1
        else:
            result.created += 1


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

        project_id = str(raw["project_id"])
        if not _is_safe_path_segment(project_id):
            result.items.append(
                ImportItemResult(
                    index=idx,
                    entity_type="projects",
                    action="skipped",
                    error=f"Unsafe project_id {project_id!r}",
                )
            )
            result.skipped += 1
            result.errors.append(
                f"projects[{i}]: unsafe project_id {project_id!r} — must be a "
                "single safe directory name (letters, digits, . _ -)"
            )
            had_errors = True
            continue
        pending.append((idx, project_id))

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

    # "tasks" must run after "projects" so a project stub exists for the tree,
    # and before "schedule" so a schedule can reference the same project id.
    if "tasks" in payload:
        lst = payload["tasks"] or []
        counts["tasks"] = len(lst)
        _import_tasks(lst, db_path=tasks_db, result=result, start_idx=idx)
        idx += len(lst)

    if "schedule" in payload:
        lst = payload["schedule"] or []
        counts["schedule"] = len(lst)
        _import_schedule(
            lst, projects_root=_proj_root, result=result, start_idx=idx
        )
        idx += len(lst)

    result.entity_counts = counts
    total_attempted = result.created + result.updated + result.skipped
    result.ok = total_attempted == 0 or (result.created + result.updated) > 0
    return result
