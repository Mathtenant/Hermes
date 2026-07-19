"""Socratic intake interview (Phase 2).

Two stages, adaptive:

1. **Router** (``qwen3:4b``) — one ``structured()`` call that classifies the
   project type and extracts any fields already answered in the free-text
   description.
2. **Deterministic question engine** — asks only what is still missing: global
   core questions, then the type-specific sizing questions and junior blind
   spots from the taxonomy. Extracted fields are never re-asked.

A non-interactive ``answers`` dict (keyed by question id) drives the engine in
tests, so the whole flow runs offline with a mocked router.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from hermes_assistant.hermes.model import IntakeResult
from hermes_assistant.hermes.project_types import (
    QuestionSpec,
    default_project_type_id,
    list_project_types,
    load_project_type,
)
from hermes_assistant.llm.roster import ModelRole, get_model

logger = logging.getLogger(__name__)

# Router's flat extraction target: classify + pull pre-answered fields.
RouterExtraction = IntakeResult  # same flat shape; project_id is filled by us

# Global core questions asked for every project type, in order. Each fills one
# list-valued IntakeResult field.
CORE_QUESTIONS: list[QuestionSpec] = [
    QuestionSpec(id="q_objectives", field="objectives", kind="core",
                 prompt="What are the concrete objectives of this project?"),
    QuestionSpec(id="q_scope", field="scope", kind="core",
                 prompt="What is explicitly in scope?"),
    QuestionSpec(id="q_boundaries", field="boundaries", kind="core",
                 prompt="What is explicitly out of scope (boundaries)?"),
    QuestionSpec(id="q_stop_criteria", field="stop_criteria", kind="core",
                 prompt="What are the stop / abort criteria?"),
    QuestionSpec(id="q_constraints", field="constraints", kind="core",
                 prompt="What constraints apply (time, budget, regulatory)?"),
    QuestionSpec(id="q_success_metrics", field="success_metrics", kind="core",
                 prompt="How will success be measured?"),
    QuestionSpec(id="q_stakeholders", field="stakeholders", kind="core",
                 prompt="Who are the key stakeholders?"),
]

Asker = Callable[[QuestionSpec], object]


class _RouterClient(Protocol):  # structural type; duck-typed in tests
    def structured(self, model: str, messages: list[dict[str, str]],
                   schema: type[IntakeResult]) -> IntakeResult: ...


# --------------------------------------------------------------------------- #
# Router (classify + extract)
# --------------------------------------------------------------------------- #
def _coerce_type(raw: str | None, available: list[str]) -> str:
    """Constrain a classified type to the taxonomy; fall back deterministically."""
    if raw and raw in available:
        return raw
    return available[0] if available else default_project_type_id()


def _route(client: _RouterClient, description: str, available: list[str]) -> IntakeResult:
    messages = [
        {
            "role": "system",
            "content": (
                "You classify a HERMES project description and extract any fields "
                "already stated. Allowed project_type values: "
                + ", ".join(available)
                + ". Only extract what is explicitly present; leave unknown fields "
                "empty. Return ONLY valid JSON."
            ),
        },
        {"role": "user", "content": description},
    ]
    return client.structured(get_model(ModelRole.ROUTER), messages, RouterExtraction)


# --------------------------------------------------------------------------- #
# Question engine
# --------------------------------------------------------------------------- #
def _needs_asking(result: IntakeResult, q: QuestionSpec) -> bool:
    """A core/sizing field already filled by the router is never re-asked."""
    if q.kind == "core":
        return not getattr(result, q.field)
    if q.kind == "sizing":
        return q.sizing_flag not in result.sizing_flags
    return True  # blind spots are always surfaced


def _apply_answer(result: IntakeResult, q: QuestionSpec, value: object) -> None:
    if value is None or value == "":
        return
    if q.kind == "sizing" and q.sizing_flag is not None:
        result.sizing_flags[q.sizing_flag] = bool(value)
    elif q.kind == "blindspot":
        result.known_unknowns.append(str(value))
    else:  # core -> list field
        items = value if isinstance(value, list) else [str(value)]
        setattr(result, q.field, [str(i) for i in items])


def _resolve_answer(
    q: QuestionSpec, answers: dict[str, object], interactive: bool, ask: Asker | None
) -> object:
    if q.id in answers:
        return answers[q.id]
    if interactive and ask is not None:
        return ask(q)
    return None


def _default_asker() -> Asker:
    import typer

    def ask(q: QuestionSpec) -> object:
        prompt = " ".join(q.prompt.split())
        if q.kind == "sizing":
            return typer.confirm(prompt, default=False)
        return typer.prompt(prompt, default="")

    return ask


def run_intake(
    description: str | None,
    project_id: str,
    interactive: bool = False,
    answers: dict[str, object] | None = None,
    *,
    client: _RouterClient | None = None,
    project_type: str | None = None,
    base_dir: str | None = None,
    ask: Asker | None = None,
) -> IntakeResult:
    """Run the intake interview and return a populated :class:`IntakeResult`.

    Args:
        description: Free-text project description. If given (with a client), the
            router classifies the type and extracts pre-answered fields.
        project_id: Stable id for the project (used for artifact paths).
        interactive: If True, missing answers are prompted via ``ask``.
        answers: Non-interactive answers keyed by question id (test path).
        client: Object exposing ``structured`` (defaults to a real OllamaClient).
        project_type: Force a project type, bypassing router classification.
        base_dir: Override the taxonomy directory (tests).
        ask: Interactive asker; defaults to a Typer prompt/confirm asker.

    Returns:
        A fully assembled IntakeResult (never re-asking extracted fields).
    """
    answers = dict(answers or {})
    available = list_project_types(base_dir)

    extraction: IntakeResult | None = None
    if description and client is not None:
        extraction = _route(client, description, available)

    chosen = (
        project_type
        or (str(answers.pop("project_type")) if "project_type" in answers else None)
        or (extraction.project_type if extraction else None)
    )
    resolved_type = _coerce_type(chosen, available)
    pt = load_project_type(resolved_type, base_dir)

    result = IntakeResult(project_id=project_id, project_type=resolved_type)
    if extraction is not None:
        for field in (
            "objectives", "scope", "boundaries", "stop_criteria",
            "constraints", "success_metrics", "known_unknowns", "stakeholders",
        ):
            setattr(result, field, list(getattr(extraction, field)))
        result.sizing_flags = dict(extraction.sizing_flags)

    if interactive and ask is None:
        ask = _default_asker()

    questions = CORE_QUESTIONS + pt.sizing_questions + pt.junior_blindspots
    for q in questions:
        if not _needs_asking(result, q):
            continue
        _apply_answer(result, q, _resolve_answer(q, answers, interactive, ask))

    return result
