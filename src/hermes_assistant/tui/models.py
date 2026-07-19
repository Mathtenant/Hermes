"""TUI data models and logic (zero textual imports — unit-testable)."""

from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel

from hermes_assistant.dashboard_html import DashboardData, WBSNode


class ProjectCard(BaseModel):
    """Row model for ProjectListScreen."""

    project_id: str
    label: str
    deadline: date | None
    pct_done: float  # 0–100, derived from closed/total WBS ratio
    n_timeline: int
    n_pendenzen: int
    n_reviews: int


class PendenzFilter(BaseModel):
    """Active filters on pendenzen list."""

    source: str | None = None   # "manual", "review", "meeting", etc.
    priority: str | None = None  # "blocker", "high", "medium", "low"
    status: str | None = None   # "open", "closed", "blocked"


def wbs_rollup(node: WBSNode) -> tuple[float, int, int]:
    """Recursively compute (pct_done, total_nodes, closed_nodes) for a WBSNode tree.

    Leaf nodes are 100 % done iff status == "closed", 0 % otherwise.
    Parent pct_done is the mean of its direct children's pct_done values.
    The parent node itself is counted in total/closed.
    """
    if not node.children:
        pct = 100.0 if node.status == "closed" else 0.0
        return (pct, 1, 1 if node.status == "closed" else 0)

    child_pcts: list[float] = []
    child_totals = 0
    child_closed = 0
    for child in node.children:
        pct, total, closed = wbs_rollup(child)
        child_pcts.append(pct)
        child_totals += total
        child_closed += closed

    parent_pct = sum(child_pcts) / len(child_pcts) if child_pcts else 0.0
    parent_closed = 1 if node.status == "closed" else 0
    return (parent_pct, child_totals + 1, child_closed + parent_closed)


def project_phase_and_deadline(project_id: str, data: DashboardData) -> tuple[str, date | None]:
    """Return (label_or_dash, max_deadline) for a project from DashboardData.

    Phase is the project's label field (populated from the folder name when no
    schedule label is set). Deadline is the latest date found in the timeline
    for that project_id.
    """
    proj = next((p for p in data.projects if p.project_id == project_id), None)
    if not proj:
        return ("—", None)

    phase = proj.label or proj.project_id or "—"

    proj_timeline = [t for t in data.timeline if t.project_id == project_id]
    deadline: date | None = None
    if proj_timeline:
        max_date_str = max(t.date for t in proj_timeline)
        try:
            deadline = date.fromisoformat(max_date_str)
        except ValueError:
            deadline = None

    return (phase, deadline)


def build_project_cards(data: DashboardData) -> list[ProjectCard]:
    """Build a ProjectCard for every project in DashboardData."""
    cards: list[ProjectCard] = []
    for proj in data.projects:
        phase, deadline = project_phase_and_deadline(proj.project_id, data)
        n_timeline = sum(1 for t in data.timeline if t.project_id == proj.project_id)
        # pct_done from WBS: rollup all root wbs nodes (no per-project filter in current model)
        if data.wbs:
            pcts = [wbs_rollup(n)[0] for n in data.wbs]
            pct_done = sum(pcts) / len(pcts)
        else:
            pct_done = 0.0
        cards.append(ProjectCard(
            project_id=proj.project_id,
            label=phase,
            deadline=deadline,
            pct_done=pct_done,
            n_timeline=n_timeline,
            n_pendenzen=len(data.pendenzen),
            n_reviews=len(data.reviews),
        ))
    return cards


def validate_safe_view(data: DashboardData) -> list[str]:
    """Structural confidentiality check on DashboardData before TUI rendering.

    Returns a list of violation strings (empty list = clean).
    Checks for forbidden field names appearing as JSON keys, confidential
    keywords, and absolute filesystem paths.
    """
    from hermes_assistant.scheduling.ics import _CONFIDENTIAL_KEYWORDS

    violations: list[str] = []
    json_str = data.model_dump_json()
    json_lower = json_str.lower()

    forbidden = frozenset([
        "raw_notes", "evidence_quote", "rationale", "fix_suggestion",
        "open_assumptions", "assumptions",
    ])
    for token in forbidden:
        # Check for the token as a JSON key (surrounded by quotes + colon)
        if f'"{token}":' in json_lower:
            violations.append(f"forbidden field '{token}' in data")

    for kw in _CONFIDENTIAL_KEYWORDS:
        if kw in json_lower:
            violations.append(f"confidential keyword '{kw}' in data")

    if re.search(r"/Users/|/home/|/private/|[A-Za-z]:\\", json_str):
        violations.append("absolute filesystem path in data")

    return violations
