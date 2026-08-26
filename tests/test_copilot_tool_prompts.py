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
