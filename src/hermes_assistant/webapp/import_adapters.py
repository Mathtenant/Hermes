"""Schema adapters for the JSON importer (C1 — Copilot schema bridge).

Maps versioned third-party schemas → native importer schema so that
``import_json.import_payload`` never sees an unsupported shape.

Adapters are registered by schema-version string via ``_register`` and
dispatched deterministically by ``adapt_payload``.  Each adapter returns a
dict whose keys are a subset of the native importer entity types
(``risks``, ``plans``, ``pendenzen``, ``projects``, ``tasks``, ``schedule``)
plus the special ``_skipped_sections`` key that lists top-level sections that
were present but have no importer mapping.
"""
from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Enum translation tables — Copilot German values → importer English values
# ---------------------------------------------------------------------------

# Copilot ``likelihood`` string → importer ``likelihood`` integer (1-5 scale)
_LIKELIHOOD_TABLE: dict[str, int] = {
    "tief": 2,
    "mittel": 3,
    "hoch": 4,
}

# Copilot ``impact`` string → importer ``severity`` string
_IMPACT_TABLE: dict[str, str] = {
    "gering": "low",
    "mittel": "medium",
    "hoch": "high",
}

# Copilot ``pendenzen.source`` → importer ``PendenzSource`` value
_PENDENZ_SOURCE_TABLE: dict[str, str] = {
    "meeting": "meeting",
    "review": "review",
    "decision_log": "decision",  # enum mismatch — normalised here
    "manual": "manual",
}

# Copilot ``wbs.status`` → ``Task.status``.
#
# NOTE the lossy step: the Task model has only open/closed/blocked, so
# ``in_progress`` collapses to ``open``. The Kanban board has three columns
# (To Do / Blocked / Done) and no in-progress lane, so nothing is lost on
# screen — but a round-trip will not return "in_progress". Synonyms are
# accepted defensively because Copilot drifts between "done" and "closed".
_TASK_STATUS_TABLE: dict[str, str] = {
    "open": "open",
    "in_progress": "open",
    "done": "closed",
    "closed": "closed",
    "blocked": "blocked",
}

# Copilot ``wbs.node_kind`` → ``Task.node_kind``. "phase" has no direct
# counterpart; it maps to "deliverable" because in a HERMES WBS a phase is the
# grouping node that holds deliverables.
_NODE_KIND_TABLE: dict[str, str] = {
    "milestone": "milestone",
    "deliverable": "deliverable",
    "task": "task",
    "subtask": "task",
    "action": "task",
    "decision": "decision",
    "phase": "deliverable",
}

# Copilot ``timeline.kind`` → ``ItemKind``; German synonyms accepted.
_TIMELINE_KIND_TABLE: dict[str, str] = {
    "milestone": "milestone",
    "meilenstein": "milestone",
    "deadline": "deadline",
    "frist": "deadline",
    "task": "task",
    "aufgabe": "task",
}

# Top-level sections in Copilot v1 that the importer cannot store.
# These are noted in ``_skipped_sections``; never silently dropped.
_COPILOT_V1_UNMAPPED_SECTIONS: tuple[str, ...] = ("open_assumptions", "decisions")

# ---------------------------------------------------------------------------
# Adapter registry
# ---------------------------------------------------------------------------

# Maps schema-version string → adapter callable.
_REGISTRY: dict[str, Any] = {}


def _register(schema_version: str):
    """Decorator: register a function as the adapter for *schema_version*."""

    def decorator(fn):
        _REGISTRY[schema_version] = fn
        return fn

    return decorator


def registered_schemas() -> frozenset[str]:
    """Return the set of currently registered schema-version strings."""
    return frozenset(_REGISTRY)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def adapt_payload(payload: dict) -> dict:
    """Dispatch to the correct adapter by ``payload["schema"]``.

    If no ``schema`` key is present the payload is assumed to be in native
    importer format and is returned unchanged.

    Parameters
    ----------
    payload:
        Parsed JSON dict.  Must be a ``dict``; ``adapt_payload`` does not
        validate types beyond this.

    Returns
    -------
    dict
        Native importer payload.  May contain ``_skipped_sections`` (list of
        str) when top-level sections were present but could not be mapped.

    Raises
    ------
    ValueError
        If ``schema`` is set but no adapter is registered for that version.
    """
    schema = payload.get("schema")
    if schema is None:
        return payload  # native format — pass through unchanged

    adapter = _REGISTRY.get(schema)
    if adapter is None:
        raise ValueError(
            f"Unsupported schema: {schema!r}. "
            f"Registered versions: {sorted(_REGISTRY)}"
        )
    return adapter(payload)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _slug(text: str) -> str:
    """Convert *text* to a deterministic URL-safe slug (max 60 chars).

    Follows the same umlaut-expansion rules as the Copilot prompt so that
    repeated imports produce identical slugs.
    """
    text = text.lower()
    text = (
        text.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text[:60]


def _strip_prefix(ref: str, prefix: str) -> str:
    """Remove *prefix* from *ref* if present; return *ref* unchanged otherwise."""
    return ref[len(prefix):] if ref.startswith(prefix) else ref


# ---------------------------------------------------------------------------
# Copilot hermes.project_state/v1 adapter
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Per-tool Copilot schemas
#
# One prompt per dashboard screen keeps each Copilot request small, which is
# both faster and markedly more schema-compliant than the monolithic
# project_state export. Note that WBS and Kanban share a single schema on
# purpose: they are two renderings of one task tree (Kanban groups it by
# status, WBS nests it by parent), so separate payloads would create two
# competing sources of truth for the same tasks.
# ---------------------------------------------------------------------------


@_register("hermes.risks/v1")
def _adapt_risks_v1(payload: dict) -> dict:
    """Map the risks-only Copilot export → native ``risks``."""
    rows = payload.get("risks")
    if rows is None:
        return {"_skipped_sections": []}
    if not isinstance(rows, list):
        raise ValueError("'risks' must be a JSON array")

    adapted: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        risk: dict[str, Any] = {"title": str(r.get("title", ""))}
        ext_ref = r.get("external_ref")
        if ext_ref:
            risk["id"] = str(ext_ref)
        risk["likelihood"] = _LIKELIHOOD_TABLE.get(
            str(r.get("likelihood", "")).lower(), 3
        )
        risk["severity"] = _IMPACT_TABLE.get(str(r.get("impact", "")).lower(), "medium")
        description = r.get("description")
        if description:
            risk["description"] = str(description)
        owner = r.get("owner")
        if owner:
            risk["owner"] = str(owner)
        adapted.append(risk)
    return {"risks": adapted, "_skipped_sections": []}


@_register("hermes.pendenzen/v1")
def _adapt_pendenzen_v1(payload: dict) -> dict:
    """Map the pendenzen-only Copilot export → native ``pendenzen``."""
    rows = payload.get("pendenzen")
    if rows is None:
        return {"_skipped_sections": []}
    if not isinstance(rows, list):
        raise ValueError("'pendenzen' must be a JSON array")

    adapted: list[dict[str, Any]] = []
    for p in rows:
        if not isinstance(p, dict):
            continue
        pend: dict[str, Any] = {"title": str(p.get("title", ""))}
        ext_ref = p.get("external_ref")
        if ext_ref:
            pend["id"] = str(ext_ref)
            pend["external_ref"] = str(ext_ref)
        pend["source"] = _PENDENZ_SOURCE_TABLE.get(
            str(p.get("source", "manual")).lower(), "manual"
        )
        for src_key, dst_key in (
            ("owner", "owner"),
            ("priority", "priority"),
            ("description", "description"),
            ("source_hint", "source_ref"),
        ):
            value = p.get(src_key)
            if value:
                pend[dst_key] = str(value)
        adapted.append(pend)
    return {"pendenzen": adapted, "_skipped_sections": []}


@_register("hermes.wbs/v1")
def _adapt_wbs_v1(payload: dict) -> dict:
    """Map the work-breakdown Copilot export → native ``tasks`` (+ project stub).

    Feeds both the WBS and Kanban screens. Unlike the ``wbs`` section of
    ``project_state/v1`` — which lands in plans.db, a store no dashboard screen
    reads — this maps to ``tasks``, which is the tree those screens render.
    """
    nodes = payload.get("wbs")
    if nodes is None:
        return {"_skipped_sections": []}
    if not isinstance(nodes, list):
        raise ValueError("'wbs' must be a JSON array")

    out: dict[str, Any] = {"_skipped_sections": []}

    project_ref = str(payload.get("project_ref") or "").strip()
    if project_ref:
        out["projects"] = [{"project_id": _strip_prefix(project_ref, "proj/")}]

    tasks: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        task: dict[str, Any] = {
            "title": str(node.get("title", "")),
            "status": _TASK_STATUS_TABLE.get(
                str(node.get("status", "open")).lower(), "open"
            ),
            "node_kind": _NODE_KIND_TABLE.get(
                str(node.get("node_kind", "task")).lower(), "task"
            ),
        }
        ext_ref = node.get("external_ref")
        if ext_ref:
            task["external_ref"] = str(ext_ref)
        parent_ref = node.get("parent_ref")
        if parent_ref:
            task["parent_ref"] = str(parent_ref)
        owner = node.get("owner")
        if owner:
            task["owner"] = str(owner)
        tasks.append(task)
    out["tasks"] = tasks
    return out


@_register("hermes.timeline/v1")
def _adapt_timeline_v1(payload: dict) -> dict:
    """Map the timeline Copilot export → native ``schedule``.

    Produces one schedule document per project, which the importer writes to
    ``<projects_root>/<project_id>/schedule.json`` — the only source the
    Timeline screen reads.
    """
    entries = payload.get("timeline")
    if entries is None:
        return {"_skipped_sections": []}
    if not isinstance(entries, list):
        raise ValueError("'timeline' must be a JSON array")

    project_ref = str(payload.get("project_ref") or "").strip()
    project_id = _strip_prefix(project_ref, "proj/") or "imported-project"

    items: list[dict[str, Any]] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        title = str(e.get("title", ""))
        item: dict[str, Any] = {
            "title": title,
            "due": str(e.get("due", "")),
            "kind": _TIMELINE_KIND_TABLE.get(
                str(e.get("kind", "milestone")).lower(), "milestone"
            ),
        }
        ext_ref = e.get("external_ref")
        item["item_id"] = _strip_prefix(str(ext_ref), "ms/") if ext_ref else _slug(title)
        note = e.get("note")
        if note:
            item["note"] = str(note)
        items.append(item)

    # Deliberately no "projects" entry: _import_schedule already creates
    # <projects_root>/<project_id>/ when it writes schedule.json. Emitting a
    # project stub as well would mean a *rejected* timeline still reported
    # "1 created", telling the user the import succeeded when the thing they
    # actually asked for was thrown away.
    return {
        "schedule": [
            {
                "project_id": project_id,
                "project_label": str(payload.get("project_label") or project_id),
                "items": items,
            }
        ],
        "_skipped_sections": [],
    }


@_register("hermes.project_state/v1")
def _adapt_project_state_v1(payload: dict) -> dict:
    """Map Copilot ``hermes.project_state/v1`` JSON → native importer dict.

    Mapping summary
    ---------------
    Copilot key          → Importer key
    ``project``          → ``projects`` (one record; ``external_ref`` → ``project_id``)
    ``wbs``              → ``plans``    (tree flattened into ordered items under one plan)
    ``risks``            → ``risks``    (German enums translated; ``external_ref`` → ``id``)
    ``pendenzen``        → ``pendenzen`` (source enum normalised; ``external_ref`` → ``id``)
    ``open_assumptions`` → ``_skipped_sections`` (not silently dropped)
    ``decisions``        → ``_skipped_sections`` (not silently dropped)

    Raises
    ------
    ValueError
        If a required structural invariant is violated (e.g. ``wbs`` present
        but ``project`` absent, making ``plan_id`` underivable).
    """
    out: dict[str, Any] = {}
    skipped: list[str] = []

    # ── project → projects ────────────────────────────────────────────────
    project_raw = payload.get("project")
    plan_id: str = "imported-project"
    if project_raw is not None:
        if not isinstance(project_raw, dict):
            raise ValueError("'project' must be a JSON object")
        ext_ref = str(project_raw.get("external_ref", ""))
        project_id = _strip_prefix(ext_ref, "proj/") or _slug(
            str(project_raw.get("title", "imported-project"))
        )
        plan_id = project_id
        out["projects"] = [{"project_id": project_id}]

    # ── wbs → plans ───────────────────────────────────────────────────────
    wbs_raw = payload.get("wbs")
    if wbs_raw is not None:
        if not isinstance(wbs_raw, list):
            raise ValueError("'wbs' must be a JSON array")
        items: list[dict[str, Any]] = []
        for order, node in enumerate(wbs_raw):
            if not isinstance(node, dict):
                continue
            item: dict[str, Any] = {
                "title": str(node.get("title", "")),
                "phase": str(node.get("node_kind", "")),
                "status": str(node.get("status", "open")),
                "order": order,
            }
            ext_ref = node.get("external_ref")
            if ext_ref:
                item["id"] = str(ext_ref)
            owner = node.get("owner")
            if owner:
                item["assignee"] = str(owner)
            items.append(item)
        out["plans"] = [
            {"plan_id": plan_id, "author": "copilot-import", "items": items}
        ]

        # Also emit the tree as `tasks`. `plans` lands in plans.db, which keeps
        # the versioned plan history but which no dashboard screen reads — so
        # on its own the whole-project export left the WBS and Kanban empty
        # while reporting success. Both are written: plans.db for history,
        # tasks.db for what is actually rendered.
        out["tasks"] = [
            {
                "title": str(node.get("title", "")),
                "status": _TASK_STATUS_TABLE.get(
                    str(node.get("status", "open")).lower(), "open"
                ),
                "node_kind": _NODE_KIND_TABLE.get(
                    str(node.get("node_kind", "task")).lower(), "task"
                ),
                **({"external_ref": str(node["external_ref"])}
                   if node.get("external_ref") else {}),
                **({"parent_ref": str(node["parent_ref"])}
                   if node.get("parent_ref") else {}),
                **({"owner": str(node["owner"])} if node.get("owner") else {}),
            }
            for node in wbs_raw
            if isinstance(node, dict)
        ]

    # ── risks — German enum translation ───────────────────────────────────
    risks_raw = payload.get("risks")
    if risks_raw is not None:
        if not isinstance(risks_raw, list):
            raise ValueError("'risks' must be a JSON array")
        adapted_risks: list[dict[str, Any]] = []
        for r in risks_raw:
            if not isinstance(r, dict):
                continue
            risk: dict[str, Any] = {"title": str(r.get("title", ""))}
            ext_ref = r.get("external_ref")
            if ext_ref:
                risk["id"] = str(ext_ref)
            raw_lh = str(r.get("likelihood", "")).lower()
            risk["likelihood"] = _LIKELIHOOD_TABLE.get(raw_lh, 3)
            raw_impact = str(r.get("impact", "")).lower()
            risk["severity"] = _IMPACT_TABLE.get(raw_impact, "medium")
            adapted_risks.append(risk)
        out["risks"] = adapted_risks

    # ── pendenzen — source enum normalisation ─────────────────────────────
    pend_raw = payload.get("pendenzen")
    if pend_raw is not None:
        if not isinstance(pend_raw, list):
            raise ValueError("'pendenzen' must be a JSON array")
        adapted_pend: list[dict[str, Any]] = []
        for p in pend_raw:
            if not isinstance(p, dict):
                continue
            pend: dict[str, Any] = {"title": str(p.get("title", ""))}
            ext_ref = p.get("external_ref")
            if ext_ref:
                pend["id"] = str(ext_ref)
            raw_source = str(p.get("source", "manual")).lower()
            pend["source"] = _PENDENZ_SOURCE_TABLE.get(raw_source, "manual")
            owner = p.get("owner")
            if owner:
                pend["owner"] = str(owner)
            adapted_pend.append(pend)
        out["pendenzen"] = adapted_pend

    # ── unmapped sections — surface, never silently drop ──────────────────
    for section in _COPILOT_V1_UNMAPPED_SECTIONS:
        if payload.get(section):
            skipped.append(section)

    out["_skipped_sections"] = skipped
    return out
