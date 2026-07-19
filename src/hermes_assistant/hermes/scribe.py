"""Scribe — pure writers for intake & plan artifacts (Phase 2).

No model calls, no side effects beyond writing the four project artifacts:
``intake.json``, ``plan.json``, ``plan.md`` and ``decisions.md``. The project
id is validated against path traversal so a malicious/typo'd id can never
escape the projects base directory.
"""

from __future__ import annotations

import re
from pathlib import Path

from hermes_assistant.hermes.model import Flag, IntakeResult, ProjectPlan

# Conservative id policy: letters, digits, dash, underscore, dot — but never a
# bare/leading dot sequence that could form "..". Anything else is rejected.
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ScribeError(ValueError):
    """Raised on an unsafe project id or write target."""


def safe_project_dir(base_dir: str | Path, project_id: str) -> Path:
    """Resolve ``base_dir/project_id`` and guarantee it stays under ``base_dir``.

    Raises:
        ScribeError: If ``project_id`` is empty, contains a path separator,
            ``..``, or otherwise resolves outside ``base_dir``.
    """
    if not project_id or not _ID_RE.match(project_id) or ".." in project_id:
        raise ScribeError(f"Unsafe project id: {project_id!r}")
    base = Path(base_dir).resolve()
    target = (base / project_id).resolve()
    # Defence in depth: even a well-formed id must not escape the base.
    if base != target and base not in target.parents:
        raise ScribeError(f"Project id escapes base directory: {project_id!r}")
    return target


def _render_plan_md(plan: ProjectPlan) -> str:
    lines: list[str] = [
        f"# {plan.title}",
        "",
        f"- **Scenario:** {plan.scenario}",
        f"- **Approach:** {plan.approach.value}",
        f"- **Roles:** {', '.join(plan.roles) if plan.roles else '_none_'}",
        "",
    ]
    for phase in plan.phases:
        lines.append(f"## Phase: {phase.name}")
        lines.append("")
        if phase.milestones:
            lines.append("### Quality gates")
            for ms in phase.milestones:
                gate = " (quality gate)" if ms.is_quality_gate else ""
                lines.append(f"- **{ms.name}**{gate}")
                for crit in ms.release_criteria:
                    lines.append(f"  - {crit}")
            lines.append("")
        if phase.outcomes:
            lines.append("### Outcomes")
            for oc in phase.outcomes:
                tag = "mandatory" if oc.mandatory else "optional"
                lines.append(f"- **{oc.name}** ({oc.kind}, {tag})")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_decisions_md(
    intake: IntakeResult, plan: ProjectPlan, flags: list[Flag] | None = None
) -> str:
    lines: list[str] = [
        "# Decision log",
        "",
        f"- **Project:** {intake.project_id}",
        f"- **Type:** {intake.project_type}",
        f"- **Approach:** {plan.approach.value}",
        "",
        "## Open assumptions",
        "",
    ]
    assumptions = plan.open_assumptions or ["_none recorded_"]
    lines.extend(f"- {a}" for a in assumptions)
    lines.append("")
    lines.append("## Known unknowns (junior blind spots)")
    lines.append("")
    unknowns = intake.known_unknowns or ["_none recorded_"]
    lines.extend(f"- {u}" for u in unknowns)
    lines.append("")
    lines.append("## Risks")
    lines.append("")
    risks = plan.risks or ["_none recorded_"]
    lines.extend(f"- {r}" for r in risks)
    lines.append("")
    lines.append("## Checker flags")
    lines.append("")
    if flags:
        for f in flags:
            lines.append(f"- [{f.severity.value}] {f.kind}: {f.detail}")
    else:
        lines.append("_none_")
    return "\n".join(lines).rstrip() + "\n"


def write_artifacts(
    base_dir: str | Path,
    intake: IntakeResult,
    plan: ProjectPlan,
    flags: list[Flag] | None = None,
) -> dict[str, Path]:
    """Write all four artifacts for ``intake.project_id`` under ``base_dir``.

    Returns:
        Mapping of artifact name -> written path.

    Raises:
        ScribeError: If the project id is unsafe.
    """
    project_dir = safe_project_dir(base_dir, intake.project_id)
    project_dir.mkdir(parents=True, exist_ok=True)

    paths = {
        "intake": project_dir / "intake.json",
        "plan": project_dir / "plan.json",
        "plan_md": project_dir / "plan.md",
        "decisions": project_dir / "decisions.md",
    }
    paths["intake"].write_text(intake.model_dump_json(indent=2), encoding="utf-8")
    paths["plan"].write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    paths["plan_md"].write_text(_render_plan_md(plan), encoding="utf-8")
    with paths["decisions"].open("a", encoding="utf-8") as fh:
        fh.write(_render_decisions_md(intake, plan, flags))
    return paths
