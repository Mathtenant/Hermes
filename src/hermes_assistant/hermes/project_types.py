"""Project-type taxonomy loader (Phase 2).

The taxonomy is data-driven: each project type is a YAML file under
``settings.project_types_path`` and the ordered phase backbone lives in
``_generic_phases.yaml``. New types are added as files, with no code changes.

``mandatory_deliverables`` is the single source of truth shared by both the
planner (which materialises outcomes) and the checker (which verifies them).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from hermes_assistant.config import settings

PHASE_SPINE_FILE = "_generic_phases.yaml"


class MilestoneSpec(BaseModel):
    """A quality-gate (or plain) milestone in the phase spine."""

    id: str
    name: str
    is_quality_gate: bool = True
    release_criteria: list[str] = []


class PhaseSpec(BaseModel):
    """A phase in the generic HERMES phase spine."""

    id: str
    name: str
    milestones: list[MilestoneSpec] = []


class DeliverableSpec(BaseModel):
    """A deliverable a project type must (conditionally) produce."""

    id: str
    name: str
    kind: str = "document"  # "document" | "state" | "decision"
    phase: str
    # None = always mandatory; otherwise the name of the sizing flag that,
    # when set, makes this deliverable mandatory.
    condition: str | None = None


class QuestionSpec(BaseModel):
    """One intake question (type-specific sizing or junior blind spot)."""

    id: str
    prompt: str
    field: str  # IntakeResult attribute the answer fills
    kind: Literal["core", "sizing", "blindspot"]
    sizing_flag: str | None = None  # set for kind == "sizing"


class ProjectType(BaseModel):
    """A HERMES project type loaded from YAML."""

    id: str
    name: str
    description: str = ""
    phases: list[str] = []  # ordered phase ids into the spine
    min_roles: list[str] = []
    deliverables: list[DeliverableSpec] = []
    sizing_questions: list[QuestionSpec] = []
    junior_blindspots: list[QuestionSpec] = []


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def _base_dir(base_dir: str | Path | None) -> Path:
    return Path(base_dir) if base_dir is not None else Path(settings.project_types_path)


def load_phase_spine(base_dir: str | Path | None = None) -> dict[str, PhaseSpec]:
    """Load the generic phase spine as an id -> PhaseSpec map.

    Raises:
        FileNotFoundError: If the spine file is missing.
    """
    path = _base_dir(base_dir) / PHASE_SPINE_FILE
    if not path.is_file():
        raise FileNotFoundError(f"Phase spine not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    phases = [PhaseSpec.model_validate(p) for p in raw.get("phases", [])]
    return {p.id: p for p in phases}


def list_project_types(base_dir: str | Path | None = None) -> list[str]:
    """Return the sorted ids of all available project types (excludes the spine)."""
    directory = _base_dir(base_dir)
    if not directory.is_dir():
        return []
    return sorted(
        p.stem
        for p in directory.glob("*.yaml")
        if not p.name.startswith("_")
    )


def load_project_type(pt_id: str, base_dir: str | Path | None = None) -> ProjectType:
    """Load a single project type by id.

    Raises:
        FileNotFoundError: If no YAML file matches ``pt_id``.
    """
    path = _base_dir(base_dir) / f"{pt_id}.yaml"
    if not path.is_file():
        available = ", ".join(list_project_types(base_dir)) or "(none)"
        raise FileNotFoundError(
            f"Unknown project type {pt_id!r}. Available: {available}"
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ProjectType.model_validate(raw)


# --------------------------------------------------------------------------- #
# Shared resolvers (single source of truth for planner + checker)
# --------------------------------------------------------------------------- #
def mandatory_deliverables(
    pt: ProjectType, sizing_flags: dict[str, bool]
) -> list[DeliverableSpec]:
    """Resolve which deliverables are mandatory given the sizing answers.

    An unconditional deliverable is always mandatory. A conditional one is
    mandatory iff its ``condition`` flag is set to ``True``. This resolver is
    the single source of truth for both ``build_plan`` and ``check_plan``.
    """
    result: list[DeliverableSpec] = []
    for spec in pt.deliverables:
        if spec.condition is None or sizing_flags.get(spec.condition, False):
            result.append(spec)
    return result


def resolve_phases(
    pt: ProjectType, spine: dict[str, PhaseSpec] | None = None
) -> list[PhaseSpec]:
    """Return the project type's phases, in declared order, from the spine.

    Raises:
        KeyError: If the type references a phase id absent from the spine.
    """
    spine = spine if spine is not None else load_phase_spine()
    phases: list[PhaseSpec] = []
    for phase_id in pt.phases:
        if phase_id not in spine:
            raise KeyError(f"Phase {phase_id!r} referenced by {pt.id!r} not in spine")
        phases.append(spine[phase_id])
    return phases


@lru_cache(maxsize=1)
def default_project_type_id() -> str:
    """Return the fallback project-type id (the first available, deterministic)."""
    available = list_project_types()
    return available[0] if available else "isds-analyse"
