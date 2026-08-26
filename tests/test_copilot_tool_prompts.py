"""Per-tool Copilot prompts: schema adapters, importers, and prompt examples.

The per-tool prompts exist so each Copilot request stays small (faster, and
markedly more schema-compliant than the monolithic project_state export). Each
prompt carries a worked "## Beispiel" block; these tests run that block through
the real adapter + importer, so a prompt that drifts out of sync with the
schema fails here instead of silently producing an unimportable export.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_assistant.dashboard_html import load_dashboard_data
from hermes_assistant.jobqueue.jobs import JobStore
from hermes_assistant.tasks.store import TaskStore
from hermes_assistant.webapp.import_adapters import adapt_payload, registered_schemas
from hermes_assistant.webapp.import_json import import_payload, validate_import_payload

_PROMPT_DIR = (
    Path(__file__).resolve().parents[1]
    / "src/hermes_assistant/webapp/static/prompts"
)

# prompt filename → schema string it documents
_TOOL_PROMPTS = {
    "copilot_risks": "hermes.risks/v1",
    "copilot_pendenzen": "hermes.pendenzen/v1",
    "copilot_wbs": "hermes.wbs/v1",
    "copilot_timeline": "hermes.timeline/v1",
}


def _extract_example(prompt_name: str) -> dict:
    """Return the JSON object under the prompt's '## Beispiel' heading."""
    text = (_PROMPT_DIR / f"{prompt_name}.txt").read_text(encoding="utf-8")
    start = text.index("## Beispiel")
    brace = text.index("{", start)
    depth = 0
    for i, ch in enumerate(text[brace:], brace):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[brace : i + 1])
    raise AssertionError(f"{prompt_name}: unbalanced braces in example block")


def _run_import(payload: dict, tmp_path: Path):
    native = adapt_payload(payload)
    native.pop("_skipped_sections", None)
    assert validate_import_payload(native) == [], native
    return import_payload(
        native,
        risks_db=str(tmp_path / "risks.db"),
        plans_db=str(tmp_path / "plans.db"),
        tasks_db=str(tmp_path / "tasks.db"),
        projects_root=str(tmp_path / "projects"),
    )


# --------------------------------------------------------------------------- #
# Prompt files stay in sync with the adapters
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("prompt_name,schema", sorted(_TOOL_PROMPTS.items()))
def test_prompt_file_exists_and_declares_its_schema(prompt_name: str, schema: str):
    text = (_PROMPT_DIR / f"{prompt_name}.txt").read_text(encoding="utf-8")
    assert f'"schema": "{schema}"' in text


@pytest.mark.parametrize("schema", sorted(_TOOL_PROMPTS.values()))
def test_schema_has_registered_adapter(schema: str):
    assert schema in registered_schemas()


@pytest.mark.parametrize("prompt_name,schema", sorted(_TOOL_PROMPTS.items()))
def test_prompt_example_imports_cleanly(prompt_name: str, schema: str, tmp_path: Path):
    """The worked example in each prompt must survive the real pipeline."""
    example = _extract_example(prompt_name)
    assert example["schema"] == schema
    result = _run_import(example, tmp_path)
    assert result.errors == []
    assert result.created > 0


@pytest.mark.parametrize("prompt_name", sorted(_TOOL_PROMPTS))
def test_prompt_example_is_idempotent(prompt_name: str, tmp_path: Path):
    """Re-importing the same export updates rather than duplicating."""
    example = _extract_example(prompt_name)
    first = _run_import(example, tmp_path)
    second = _run_import(example, tmp_path)
    assert second.created == 0, f"{prompt_name} duplicated on re-import"
    assert second.updated == first.created


# --------------------------------------------------------------------------- #
# The whole point: these payloads must reach the screens
# --------------------------------------------------------------------------- #


def test_wbs_export_populates_wbs_and_kanban(tmp_path: Path):
    """One work-breakdown export feeds both screens — they share a task tree.

    Children are listed before their parents to prove the importer orders by
    dependency rather than trusting array order.
    """
    payload = {
        "schema": "hermes.wbs/v1",
        "project_ref": "proj/webshop",
        "wbs": [
            {
                "external_ref": "wp/checkout",
                "parent_ref": "wp/realisierung",
                "title": "Checkout",
                "node_kind": "task",
                "status": "in_progress",
            },
            {
                "external_ref": "wp/realisierung",
                "title": "Realisierung",
                "node_kind": "phase",
                "status": "open",
            },
            {
                "external_ref": "wp/abnahme",
                "title": "Abnahme",
                "node_kind": "deliverable",
                "status": "done",
            },
        ],
    }
    assert _run_import(payload, tmp_path).errors == []

    store = TaskStore(str(tmp_path / "tasks.db"))
    try:
        data = load_dashboard_data(
            task_store=store,
            job_store=JobStore(":memory:"),
            risk_registry=None,
            projects_root=tmp_path / "projects",
        )
    finally:
        store.close()

    # WBS: nested, child under its parent despite the payload ordering.
    roots = {n.title: n for n in data.wbs}
    assert set(roots) == {"Realisierung", "Abnahme"}
    assert [c.title for c in roots["Realisierung"].children] == ["Checkout"]

    # Kanban: the same tasks, grouped by status.
    columns = {c.label: [card.title for card in c.cards] for c in data.kanban}
    assert columns["Done"] == ["Abnahme"]
    assert sorted(columns["To Do"]) == ["Checkout", "Realisierung"]


def test_timeline_export_populates_timeline(tmp_path: Path):
    payload = {
        "schema": "hermes.timeline/v1",
        "project_ref": "proj/webshop",
        "timeline": [
            {"external_ref": "ms/go-live", "title": "Go-Live",
             "due": "2099-11-30", "kind": "milestone"},
            {"external_ref": "ms/abnahme", "title": "Abnahme",
             "due": "2099-10-15", "kind": "deadline"},
        ],
    }
    assert _run_import(payload, tmp_path).errors == []
    assert (tmp_path / "projects" / "webshop" / "schedule.json").is_file()

    store = TaskStore(str(tmp_path / "tasks.db"))
    try:
        data = load_dashboard_data(
            task_store=store,
            job_store=JobStore(":memory:"),
            risk_registry=None,
            projects_root=tmp_path / "projects",
        )
    finally:
        store.close()

    assert [(e.date, e.label, e.kind) for e in data.timeline] == [
        ("2099-10-15", "Abnahme", "deadline"),
        ("2099-11-30", "Go-Live", "milestone"),
    ]


# --------------------------------------------------------------------------- #
# Structural failures are rejected, not silently flattened
# --------------------------------------------------------------------------- #


def test_wbs_rejects_dangling_parent_ref(tmp_path: Path):
    """A parent_ref with no matching node must fail loudly.

    Silently flattening it would produce a WBS that looks plausible but is
    structurally wrong — far worse than a rejected import.
    """
    payload = {
        "schema": "hermes.wbs/v1",
        "wbs": [
            {"external_ref": "wp/child", "parent_ref": "wp/ghost",
             "title": "Orphan", "node_kind": "task", "status": "open"},
        ],
    }
    native = adapt_payload(payload)
    native.pop("_skipped_sections", None)
    result = import_payload(
        native,
        tasks_db=str(tmp_path / "tasks.db"),
        projects_root=str(tmp_path / "projects"),
    )
    assert result.created == 0
    assert any("wp/ghost" in e for e in result.errors), result.errors


def test_wbs_rejects_parent_ref_cycle(tmp_path: Path):
    payload = {
        "schema": "hermes.wbs/v1",
        "wbs": [
            {"external_ref": "wp/a", "parent_ref": "wp/b", "title": "A",
             "node_kind": "task", "status": "open"},
            {"external_ref": "wp/b", "parent_ref": "wp/a", "title": "B",
             "node_kind": "task", "status": "open"},
        ],
    }
    native = adapt_payload(payload)
    native.pop("_skipped_sections", None)
    result = import_payload(
        native,
        tasks_db=str(tmp_path / "tasks.db"),
        projects_root=str(tmp_path / "projects"),
    )
    assert result.created == 0
    assert any("cycle" in e.lower() for e in result.errors), result.errors


def test_timeline_rejects_unparseable_due_date(tmp_path: Path):
    """'Q4' and friends must be refused — the Timeline sorts dates as strings."""
    payload = {
        "schema": "hermes.timeline/v1",
        "project_ref": "proj/webshop",
        "timeline": [{"external_ref": "ms/x", "title": "Go-Live",
                      "due": "Q4 2026", "kind": "milestone"}],
    }
    native = adapt_payload(payload)
    native.pop("_skipped_sections", None)
    result = import_payload(
        native,
        tasks_db=str(tmp_path / "tasks.db"),
        projects_root=str(tmp_path / "projects"),
    )
    assert result.created == 0
    assert any("YYYY-MM-DD" in e for e in result.errors), result.errors
    # Nothing written: a rejected schedule must not clobber the existing one.
    assert not (tmp_path / "projects" / "webshop" / "schedule.json").exists()


def test_task_status_enum_is_validated(tmp_path: Path):
    payload = {"tasks": [{"title": "X", "status": "wip"}]}
    result = import_payload(
        payload,
        tasks_db=str(tmp_path / "tasks.db"),
        projects_root=str(tmp_path / "projects"),
    )
    assert result.created == 0
    assert any("status" in e for e in result.errors), result.errors


# --------------------------------------------------------------------------- #
# Hardening: edge cases that took the system down before, each verified
# against the real pipeline rather than reasoned about.
# --------------------------------------------------------------------------- #


def test_poisoned_text_cannot_break_the_dashboard(tmp_path: Path):
    """An email in imported text must not 500 /api/dashboard forever.

    Rows are stored verbatim and every dashboard response is scanned by the
    confidentiality guard, so one meeting-derived pendenz naming somebody by
    address would make the whole screen unreachable until the DB was edited by
    hand. The address is redacted at import and the change is reported.
    """
    from hermes_assistant.webapp.server import _validate_safe_json

    payload = {
        "schema": "hermes.pendenzen/v1",
        "pendenzen": [
            {"external_ref": "pd/a", "source": "meeting",
             "title": "Klärung mit hans.muster@example.com"},
            {"external_ref": "pd/b", "source": "review",
             "title": "Ablage nach /Users/muster/geheim/plan.docx prüfen"},
        ],
    }
    result = _run_import(payload, tmp_path)
    assert result.created == 2

    store = TaskStore(str(tmp_path / "tasks.db"))
    try:
        data = load_dashboard_data(
            task_store=store,
            job_store=JobStore(":memory:"),
            risk_registry=None,
            projects_root=tmp_path / "projects",
        )
    finally:
        store.close()

    # The dashboard payload must pass the very guard that would 500 it.
    assert _validate_safe_json(data.model_dump_json()) == []
    titles = " ".join(p.title for p in data.pendenzen)
    assert "hans.muster@example.com" not in titles
    assert "/Users/muster" not in titles
    # Redaction is reported, never silent.
    assert any("E-Mail" in e for e in result.errors), result.errors
    assert any("Dateipfad" in e for e in result.errors), result.errors


def test_schedule_rejects_path_traversal(tmp_path: Path):
    """A project_ref must not be able to write outside the projects root."""
    payload = {
        "schema": "hermes.timeline/v1",
        "project_ref": "proj/../../escaped",
        "timeline": [{"external_ref": "ms/a", "title": "A",
                      "due": "2026-01-01", "kind": "milestone"}],
    }
    native = adapt_payload(payload)
    native.pop("_skipped_sections", None)
    result = import_payload(
        native,
        tasks_db=str(tmp_path / "tasks.db"),
        projects_root=str(tmp_path / "projects"),
    )
    assert result.created == 0
    assert any("project_id" in e for e in result.errors), result.errors
    assert list(tmp_path.rglob("schedule.json")) == []


def test_projects_rejects_path_traversal(tmp_path: Path):
    result = import_payload(
        {"projects": [{"project_id": "../../escaped"}]},
        projects_root=str(tmp_path / "projects"),
    )
    assert result.created == 0
    assert any("project_id" in e for e in result.errors), result.errors
    assert not (tmp_path / "escaped").exists()


def test_schedule_rejects_impossible_calendar_date(tmp_path: Path):
    """'2026-02-30' matches YYYY-MM-DD but is not a real date."""
    payload = {
        "schema": "hermes.timeline/v1",
        "project_ref": "proj/webshop",
        "timeline": [{"external_ref": "ms/a", "title": "A",
                      "due": "2026-02-30", "kind": "milestone"}],
    }
    native = adapt_payload(payload)
    native.pop("_skipped_sections", None)
    # Must be a reported validation error, never an uncaught ValueError.
    result = import_payload(
        native,
        tasks_db=str(tmp_path / "tasks.db"),
        projects_root=str(tmp_path / "projects"),
    )
    assert result.created == 0
    assert any("calendar date" in e for e in result.errors), result.errors


def test_duplicate_external_ref_is_rejected_not_dropped(tmp_path: Path):
    """Truncated slugs can collide; losing a row silently is worse than failing."""
    payload = {
        "schema": "hermes.wbs/v1",
        "wbs": [
            {"external_ref": "wp/dup", "title": "First",
             "node_kind": "task", "status": "open"},
            {"external_ref": "wp/dup", "title": "Second",
             "node_kind": "task", "status": "open"},
        ],
    }
    native = adapt_payload(payload)
    native.pop("_skipped_sections", None)
    result = import_payload(
        native,
        tasks_db=str(tmp_path / "tasks.db"),
        projects_root=str(tmp_path / "projects"),
    )
    assert result.created == 0
    assert any("duplicate external_ref" in e for e in result.errors), result.errors


def test_child_can_attach_to_an_already_imported_parent(tmp_path: Path):
    """Incremental exports are the normal workflow, not an edge case.

    A second export carrying only new work must be able to hang it off a tree
    imported earlier, rather than being rejected as a dangling parent_ref.
    """
    _run_import(
        {"schema": "hermes.wbs/v1", "wbs": [
            {"external_ref": "wp/root", "title": "Root",
             "node_kind": "phase", "status": "open"}]},
        tmp_path,
    )
    result = _run_import(
        {"schema": "hermes.wbs/v1", "wbs": [
            {"external_ref": "wp/kid", "parent_ref": "wp/root", "title": "Kid",
             "node_kind": "task", "status": "open"}]},
        tmp_path,
    )
    assert result.errors == []
    assert result.created == 1

    store = TaskStore(str(tmp_path / "tasks.db"))
    try:
        data = load_dashboard_data(
            task_store=store,
            job_store=JobStore(":memory:"),
            risk_registry=None,
            projects_root=tmp_path / "projects",
        )
    finally:
        store.close()
    assert [n.title for n in data.wbs] == ["Root"]
    assert [c.title for c in data.wbs[0].children] == ["Kid"]


def test_deep_child_first_tree_does_not_blow_the_stack(tmp_path: Path):
    """The prompt allows children before parents, so depth must be iterative.

    A recursive ordering pass overflowed at roughly 2 000 nodes, turning a
    large but perfectly legal export into an HTTP 500.
    """
    depth = 3000
    chain = [
        {"external_ref": f"wp/n{i}",
         "parent_ref": (f"wp/n{i - 1}" if i else None),
         "title": f"N{i}", "node_kind": "task", "status": "open"}
        for i in range(depth)
    ]
    chain.reverse()
    result = _run_import({"schema": "hermes.wbs/v1", "wbs": chain}, tmp_path)
    assert result.errors == []
    assert result.created == depth


# --------------------------------------------------------------------------- #
# Tolerating the output language models actually produce.
#
# The prompts forbid code fences and prose, but models emit them anyway. A bare
# "Expecting value: line 1 column 1" gives the user nothing to act on, and this
# is the single likeliest failure of the whole Copilot workflow.
# --------------------------------------------------------------------------- #


def test_strict_json_takes_the_fast_path_unrepaired():
    from hermes_assistant.webapp.import_json import loads_forgiving

    payload, repairs = loads_forgiving('{"risks":[{"title":"Clean"}]}')
    assert payload["risks"][0]["title"] == "Clean"
    assert repairs == []


@pytest.mark.parametrize(
    "raw,expected_title,expected_repair",
    [
        ('```json\n{"risks":[{"title":"Fenced"}]}\n```',
         "Fenced", "Code-Fence"),
        ('Here is the JSON you requested:\n{"risks":[{"title":"Prose"}]}\nHope that helps!',
         "Prose", "Text vor/nach"),
        ('{"risks":[{"title":"Trailing"},]}',
         "Trailing", "Kommas"),
    ],
)
def test_common_llm_wrappers_are_repaired(raw, expected_title, expected_repair):
    from hermes_assistant.webapp.import_json import loads_forgiving

    payload, repairs = loads_forgiving(raw)
    assert payload["risks"][0]["title"] == expected_title
    assert any(expected_repair in r for r in repairs), repairs


def test_repair_never_rewrites_string_contents():
    """A comma before '}' *inside a value* must survive untouched.

    A regex-based trailing-comma fix would silently corrupt this title, turning
    a syntax repair into data loss.
    """
    from hermes_assistant.webapp.import_json import loads_forgiving

    payload, repairs = loads_forgiving('{"risks":[{"title":"Abnahme, }"}]}')
    assert payload["risks"][0]["title"] == "Abnahme, }"
    assert repairs == []


def test_unsalvageable_input_still_raises():
    import json as _json

    from hermes_assistant.webapp.import_json import loads_forgiving

    with pytest.raises(_json.JSONDecodeError):
        loads_forgiving("this is not json at all")


# --------------------------------------------------------------------------- #
# Re-import must apply structural corrections.
#
# Reported symptom: "0 created, 66 updated" and nothing visibly changed. Two
# separate causes, both covered here and in the UI tests.
# --------------------------------------------------------------------------- #


def _wbs(nodes):
    return {"schema": "hermes.wbs/v1", "wbs": nodes}


def _tree(tmp_path: Path):
    store = TaskStore(str(tmp_path / "tasks.db"))
    try:
        data = load_dashboard_data(
            task_store=store,
            job_store=JobStore(":memory:"),
            risk_registry=None,
            projects_root=tmp_path / "projects",
        )
    finally:
        store.close()
    return {n.title: [(c.title, c.wbs_number, c.kind) for c in n.children]
            for n in data.wbs}


def test_reimport_applies_reparenting(tmp_path: Path):
    """Moving a node to a different parent must take effect on re-import.

    ``update()`` writes the blob but syncs only the status column, so assigning
    parent_id through it left the indexed column — the one the tree is read
    from — pointing at the old parent. The import reported "updated" while the
    WBS on screen never moved.
    """
    base = [
        {"external_ref": "wp/a", "title": "Phase A", "node_kind": "phase", "status": "open"},
        {"external_ref": "wp/b", "title": "Phase B", "node_kind": "phase", "status": "open"},
    ]
    _run_import(_wbs([*base, {
        "external_ref": "wp/x", "parent_ref": "wp/a", "title": "Task X",
        "node_kind": "task", "status": "open"}]), tmp_path)
    assert [t for t, _, _ in _tree(tmp_path)["Phase A"]] == ["Task X"]

    result = _run_import(_wbs([*base, {
        "external_ref": "wp/x", "parent_ref": "wp/b", "title": "Task X",
        "node_kind": "task", "status": "open"}]), tmp_path)
    assert result.created == 0 and result.updated == 3

    tree = _tree(tmp_path)
    assert tree["Phase A"] == []
    assert [t for t, _, _ in tree["Phase B"]] == ["Task X"]


def test_reimport_recomputes_wbs_numbers_after_a_move(tmp_path: Path):
    """A WBS number encodes the path, so a move must renumber the subtree."""
    base = [
        {"external_ref": "wp/a", "title": "Phase A", "node_kind": "phase", "status": "open"},
        {"external_ref": "wp/b", "title": "Phase B", "node_kind": "phase", "status": "open"},
    ]
    _run_import(_wbs([*base, {
        "external_ref": "wp/x", "parent_ref": "wp/a", "title": "Task X",
        "node_kind": "task", "status": "open"}]), tmp_path)
    assert _tree(tmp_path)["Phase A"][0][1] == "1.1"

    _run_import(_wbs([*base, {
        "external_ref": "wp/x", "parent_ref": "wp/b", "title": "Task X",
        "node_kind": "task", "status": "open"}]), tmp_path)
    assert _tree(tmp_path)["Phase B"][0][1] == "2.1"


def test_reimport_applies_node_kind_change(tmp_path: Path):
    base = [{"external_ref": "wp/a", "title": "Phase A",
             "node_kind": "phase", "status": "open"}]
    _run_import(_wbs([*base, {
        "external_ref": "wp/x", "parent_ref": "wp/a", "title": "X",
        "node_kind": "task", "status": "open"}]), tmp_path)
    assert _tree(tmp_path)["Phase A"][0][2] == "task"

    _run_import(_wbs([*base, {
        "external_ref": "wp/x", "parent_ref": "wp/a", "title": "X",
        "node_kind": "deliverable", "status": "open"}]), tmp_path)
    assert _tree(tmp_path)["Phase A"][0][2] == "deliverable"


def test_set_parent_refuses_to_create_a_cycle(tmp_path: Path):
    """Moving a node under its own descendant would detach the subtree."""
    _run_import(_wbs([
        {"external_ref": "wp/a", "title": "A", "node_kind": "phase", "status": "open"},
        {"external_ref": "wp/b", "parent_ref": "wp/a", "title": "B",
         "node_kind": "task", "status": "open"},
    ]), tmp_path)

    store = TaskStore(str(tmp_path / "tasks.db"))
    try:
        a = store.find_by_external_ref("wp/a")
        b = store.find_by_external_ref("wp/b")
        with pytest.raises(ValueError):
            store.set_parent(a.id, b.id)
    finally:
        store.close()


def test_full_export_also_populates_wbs_and_kanban(tmp_path: Path):
    """The whole-project export must reach the screens too.

    Its `wbs` section maps to `plans` → plans.db, which no dashboard screen
    reads; on its own that reported success and left WBS and Kanban empty.
    """
    payload = {
        "schema": "hermes.project_state/v1",
        "project": {"external_ref": "proj/demo", "title": "Demo"},
        "wbs": [
            {"external_ref": "wp/root", "title": "Realisierung",
             "node_kind": "phase", "status": "open"},
            {"external_ref": "wp/kid", "parent_ref": "wp/root", "title": "Checkout",
             "node_kind": "task", "status": "open"},
        ],
    }
    result = _run_import(payload, tmp_path)
    assert result.entity_counts.get("plans") == 1   # history preserved
    assert result.entity_counts.get("tasks") == 2   # and now rendered

    tree = _tree(tmp_path)
    assert [t for t, _, _ in tree["Realisierung"]] == ["Checkout"]
