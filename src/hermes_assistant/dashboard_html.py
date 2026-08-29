"""Static HTML dashboard for HERMES local assistant (Part IV-J §31K, Phase 3.6)."""

from __future__ import annotations

import html as _html
import re
import string
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from hermes_assistant._dashboard_assets import _CSS, _JS
from hermes_assistant.scheduling.ics import _CONFIDENTIAL_KEYWORDS

# ---------------------------------------------------------------------------
# Confidentiality guard
# ---------------------------------------------------------------------------

class ConfidentialityError(Exception):
    """Raised when validate_safe_export detects a violation in rendered output."""

    def __init__(self, violations: list[str]) -> None:
        self.violations = violations
        super().__init__("; ".join(violations))


_FORBIDDEN_FIELDS = frozenset(
    ["raw_notes", "evidence_quote", "rationale", "fix_suggestion", "open_assumptions", "assumptions"]
)
_FS_RE = re.compile(r"(/Users/|/home/|/private/|[A-Z]:\\\\)")
_EXT_URL_RE = re.compile(r"https?://(?!localhost)")
_ENDTAG_RE = re.compile(r"</", re.IGNORECASE)


def esc(s: str | None) -> str:
    """HTML-escape ``s``; return empty string for None."""
    return _html.escape(str(s), quote=True) if s is not None else ""


# ---------------------------------------------------------------------------
# View models — extra="forbid" blocks accidental confidential-field inclusion
# ---------------------------------------------------------------------------

class TimelineEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: str
    label: str
    kind: Literal["milestone", "deadline", "task"] = "task"
    status: Literal["open", "closed", "blocked", "future"] = "future"
    project_id: str = ""


class KanbanCard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    owner: str = ""
    wbs_number: str = ""
    priority: str = ""
    kind: str = "task"


class KanbanColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    label: str
    cards: list[KanbanCard] = Field(default_factory=list)
    overflow: int = 0


class WBSNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    wbs_number: str
    title: str
    kind: str
    status: str
    owner: str = ""
    children: list[WBSNode] = Field(default_factory=list)


WBSNode.model_rebuild()


class PendenzRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    source: str
    priority: str
    status: str
    owner: str = ""
    due_date: str = ""
    source_ref: str = ""


_PRIORITY_RANK: dict[str, int] = {"blocker": 0, "high": 1, "medium": 2, "low": 3}


class ReviewSummaryRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    rubric_id: str
    verdict: str
    blockers: int
    majors: int
    minors: int
    deliverable: str


_SEVERITY_WEIGHT: dict[str, int] = {"low": 1, "medium": 2, "high": 3, "critical": 4}


class RiskRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    severity: str
    likelihood: int
    status: str
    score: int
    updated_at: str


class GanttRow(BaseModel):
    """One bar (or diamond) in the Projektablaufplan view.

    Distinct from ``TimelineEntry``, which is a *point* derived from a due date
    and whose ``status`` is inferred from whether that date has passed. A flow
    plan carries a real span and a stated status, and conflating the two would
    mean either losing the span or overwriting a plan's own "laufend" with a
    date comparison.
    """

    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    phase: str = ""
    # Three marks, because the sweep produces three shapes of thing:
    #   vorgang     — has a span, draws as a bar
    #   meilenstein — a project gate, draws as a diamond
    #   termin      — a dated obligation with no span (a to-do with a deadline).
    # Without the third, every dated to-do rendered as a milestone diamond and
    # became indistinguishable from a Go-Live.
    kind: Literal["vorgang", "meilenstein", "termin"] = "vorgang"
    start: str = ""            # YYYY-MM-DD; empty for a milestone
    end: str                   # YYYY-MM-DD; the milestone's date, or the bar's end
    owner: str = ""
    status: Literal["offen", "laufend", "erledigt", "blockiert"] = "offen"
    progress_pct: int | None = None
    project_id: str = ""
    # Altitude and provenance, for the cross-source sweep: which document a
    # date came from, and whether the row is a gate or a single errand.
    level: Literal["meilenstein", "arbeitspaket", "aufgabe"] = "arbeitspaket"
    source_hint: str = ""


class DecisionRow(BaseModel):
    """One Beschluss, plus how many Pendenzen it set in motion.

    The decision's *Begründung* is deliberately absent. It is imported and
    stored on the ``Beschluss`` node, but ``rationale`` is in the API guard's
    ``_FORBIDDEN_FIELDS`` — where it guards the critic's internal reasoning —
    and a field named that in any response is a structural violation, i.e. a
    hard 500 rather than a redaction. Renaming it to slip past a name-based
    blocklist would hollow the guard out, and the free-text justification is
    also the part of a Beschlussliste most likely to quote confidential
    material. The title, the deciding body, the date and the affected area are
    what a lead reads at a glance; the reasoning stays in the source document.
    """

    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    decided_on: str = ""       # YYYY-MM-DD
    decided_by: str = ""
    decision_status: Literal[
        "beschlossen", "umgesetzt", "aufgehoben", "vertagt"
    ] = "beschlossen"
    affects: str = ""
    pendenzen_total: int = 0
    pendenzen_open: int = 0


class ProjectSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str
    label: str = ""


class DashboardData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generated_at: str
    scope: str = "all projects"
    range_start: str = ""
    range_end: str = ""
    projects: list[ProjectSummary] = Field(default_factory=list)
    timeline: list[TimelineEntry] = Field(default_factory=list)
    kanban: list[KanbanColumn] = Field(default_factory=list)
    wbs: list[WBSNode] = Field(default_factory=list)
    pendenzen: list[PendenzRow] = Field(default_factory=list)
    reviews: list[ReviewSummaryRow] = Field(default_factory=list)
    risks: list[RiskRow] = Field(default_factory=list)
    ablaufplan: list[GanttRow] = Field(default_factory=list)
    decisions: list[DecisionRow] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# HTML page template (@@-delimited to avoid CSS/JS $ collisions)
# ---------------------------------------------------------------------------

class _DashTemplate(string.Template):
    delimiter = "@@"
    idpattern = r"(?a:[a-z][a-z_]*)"


_PAGE = _DashTemplate("""\
<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:;">
<title>@@title</title>
<style>@@css</style>
</head>
<body>
<header class="topbar">
<h1>HERMES Dashboard</h1>
<span class="scope">@@scope</span>
<span class="range">@@range_start–@@range_end</span>
<nav><a href="#timeline">Timeline</a> <a href="#kanban">Board</a> <a href="#pendenzen">Pendenzen</a></nav>
<button id="theme-toggle" aria-pressed="false">Dark</button>
</header>
<main>
<section id="timeline"><h2>Grob-Zeitstrahl</h2>@@timeline</section>
<section id="kanban"><h2>Detail-Board</h2>@@kanban</section>
<section id="pendenzen"><h2>Pendenzen</h2>@@pendenzen</section>
<section id="wbs"><h2>WBS</h2>@@wbs</section>
<section id="reviews"><h2>Reviews</h2>@@reviews</section>
</main>
<footer>@@footer</footer>
<script type="application/json" id="dashboard-data">@@embedded_json</script>
<script>@@js</script>
</body>
</html>""")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _gantt_kind(item: Any) -> str:
    """Pick the mark for one scheduled item: bar, diamond or tick.

    ``level`` decides first, because it is what the cross-source sweep actually
    states. Falling back to "has a start?" alone would turn every dated to-do
    into a milestone diamond — the sweep is full of them, and a Go-Live must
    not look like "check an invoice by Friday".
    """
    from hermes_assistant.scheduling.model import ItemKind

    level = getattr(item, "level", "arbeitspaket")
    if level == "meilenstein" or item.kind is ItemKind.milestone:
        return "meilenstein"
    if item.start:
        return "vorgang"
    return "termin"


def _to_kanban_card(t: Any) -> KanbanCard:
    prio = ""
    if hasattr(t, "metadata") and isinstance(t.metadata, dict):
        prio = str(t.metadata.get("priority", ""))
    return KanbanCard(id=t.id, title=t.title, owner=t.owner or "", wbs_number=t.wbs_number, priority=prio, kind=t.node_kind)


def _build_wbs_node(t: Any, ts: Any) -> WBSNode:
    children_raw = ts.list_by_parent(t.id)
    tree_children = [c for c in children_raw if c.node_kind not in ("pendenz", "assumption")]
    sorted_children = sorted(tree_children, key=lambda x: x.wbs_number or "")
    return WBSNode(
        id=t.id, wbs_number=t.wbs_number, title=t.title, kind=t.node_kind,
        status=t.status, owner=t.owner or "",
        children=[_build_wbs_node(c, ts) for c in sorted_children],
    )


def _to_pendenz_row(t: Any) -> PendenzRow:
    try:
        from hermes_assistant.tasks.pendenzen import Pendenz as _PendenzModel
        p = _PendenzModel.model_validate(t.model_dump())
        return PendenzRow(
            id=t.id, title=t.title, source=p.source.value, priority=p.priority,
            status=t.status, owner=t.owner or "",
            due_date=str(p.due_date) if p.due_date else "", source_ref=p.source_ref or "",
        )
    except Exception:  # noqa: BLE001
        return PendenzRow(id=t.id, title=t.title, source="manual", priority="medium", status=t.status)


# ---------------------------------------------------------------------------
# Data loader
# ---------------------------------------------------------------------------

def load_dashboard_data(
    project_id: str | None = None,
    *,
    task_store: Any | None = None,
    job_store: Any | None = None,
    risk_registry: Any | None = None,
    projects_root: Path | None = None,
    now: datetime | None = None,
) -> DashboardData:
    """Build DashboardData from task/job stores and schedule JSON files."""
    from hermes_assistant.config import settings
    from hermes_assistant.jobqueue.jobs import JobStatus
    from hermes_assistant.jobqueue.jobs import JobStore as _JobStore
    from hermes_assistant.scheduling.model import ItemKind, Schedule
    from hermes_assistant.tasks.store import TaskStore as _TaskStore

    _now = now or datetime.now(UTC)
    _root = projects_root if projects_root is not None else Path(settings.projects_path)
    _ts: Any = task_store if task_store is not None else _TaskStore(settings.tasks_db_path)
    _js: Any = job_store if job_store is not None else _JobStore(settings.queue_db_path)

    # BFS over all tasks
    all_tasks: list[Any] = []
    pending_q = list(_ts.list_by_parent(None))
    seen: set[str] = set()
    while pending_q:
        t = pending_q.pop(0)
        if t.id in seen:
            continue
        seen.add(t.id)
        all_tasks.append(t)
        for cid in (t.children_ids or []):
            child = _ts.get(cid)
            if child and child.id not in seen:
                pending_q.append(child)

    # "assumption" kind nodes hold internal planning notes — exclude from rendered output.
    # "decision" is excluded too: a Beschluss is a settled fact, not a work
    # package, so it belongs on neither the board nor the structure tree.
    tree_tasks = [
        t for t in all_tasks
        if t.node_kind not in ("pendenz", "assumption", "decision")
    ]
    raw_pendenzen = [t for t in all_tasks if t.node_kind == "pendenz"]
    raw_decisions = [t for t in all_tasks if t.node_kind == "decision"]

    # Kanban
    _kanban_cap = 50
    open_cards = [_to_kanban_card(t) for t in tree_tasks if t.status == "open"]
    blocked_cards = [_to_kanban_card(t) for t in tree_tasks if t.status == "blocked"]
    closed_all = [t for t in tree_tasks if t.status == "closed"]
    overflow = max(0, len(closed_all) - _kanban_cap)
    closed_cards = [_to_kanban_card(t) for t in closed_all[:_kanban_cap]]
    kanban = [
        KanbanColumn(status="open", label="To Do", cards=open_cards),
        KanbanColumn(status="blocked", label="Blocked", cards=blocked_cards),
        KanbanColumn(status="closed", label="Done", cards=closed_cards, overflow=overflow),
    ]

    # WBS
    root_tasks = sorted([t for t in tree_tasks if t.parent_id is None], key=lambda x: x.wbs_number or "")
    wbs = [_build_wbs_node(t, _ts) for t in root_tasks]

    # Pendenzen sorted by (priority_rank, due_date, id)
    def _pkey(t: Any) -> tuple:
        row = _to_pendenz_row(t)
        return (_PRIORITY_RANK.get(row.priority, 99), row.due_date or "9999-99-99", t.id)

    pend_rows = [_to_pendenz_row(t) for t in sorted(raw_pendenzen, key=_pkey)]

    # Decisions (Beschlüsse), with the Pendenzen each one set in motion.
    # Pendenz.source_ref carries the raising decision's external_ref, which is
    # what lets a Beschluss show its follow-up load instead of standing alone.
    _pend_by_source: dict[str, list[Any]] = {}
    for t in raw_pendenzen:
        ref = getattr(t, "source_ref", None)
        if ref:
            _pend_by_source.setdefault(str(ref), []).append(t)

    decisions: list[DecisionRow] = []
    for t in raw_decisions:
        spawned = _pend_by_source.get(str(t.external_ref or ""), [])
        decided_on = getattr(t, "decided_on", None)
        decisions.append(
            DecisionRow(
                id=t.id,
                title=t.title,
                decided_on=str(decided_on) if decided_on else "",
                decided_by=str(getattr(t, "decided_by", "") or ""),
                decision_status=getattr(t, "decision_status", "beschlossen") or "beschlossen",
                affects=str(getattr(t, "affects", "") or ""),
                pendenzen_total=len(spawned),
                pendenzen_open=sum(1 for p in spawned if p.status != "closed"),
            )
        )
    # Newest decision first — the recent ones are the ones still being acted on.
    decisions.sort(key=lambda d: (d.decided_on or "0000-00-00", d.title), reverse=True)

    # Timeline from schedule.json
    timeline: list[TimelineEntry] = []
    ablaufplan: list[GanttRow] = []
    today_str = str(_now.date())
    if _root.is_dir():
        for proj_dir in sorted(_root.iterdir()):
            if not proj_dir.is_dir():
                continue
            sched_file = proj_dir / "schedule.json"
            if not sched_file.is_file():
                continue
            try:
                sched = Schedule.model_validate_json(sched_file.read_text(encoding="utf-8"))
                for item in sched.items:
                    # Negative-float items are "blocked" regardless of their due date.
                    # Check negative_float BEFORE the closed/future date comparison so
                    # that items which exceed the hard deadline always render red in TUI.
                    if item.item_id in sched.negative_float:
                        tl_status: Literal["open", "closed", "blocked", "future"] = "blocked"
                    elif str(item.due) < today_str:
                        tl_status = "closed"
                    else:
                        tl_status = "future"
                    tl_kind: Literal["milestone", "deadline", "task"] = item.kind.value
                    timeline.append(TimelineEntry(date=str(item.due), label=item.title, kind=tl_kind, status=tl_status, project_id=sched.project_id))

                    # Same items, read as spans rather than points. A bar needs
                    # a start; a milestone deliberately has none, and the plan's
                    # own status is kept rather than re-derived from the date —
                    # an overdue task is late, not finished.
                    ablaufplan.append(
                        GanttRow(
                            id=item.item_id,
                            title=item.title,
                            phase=getattr(item, "phase", "") or "",
                            kind=_gantt_kind(item),
                            start=str(item.start) if item.start else "",
                            end=str(item.due),
                            owner=getattr(item, "owner", None) or "",
                            status=getattr(item, "status", "offen") or "offen",
                            progress_pct=getattr(item, "progress_pct", None),
                            project_id=sched.project_id,
                            level=getattr(item, "level", "arbeitspaket") or "arbeitspaket",
                            source_hint=getattr(item, "source_hint", "") or "",
                        )
                    )
            except Exception:  # noqa: BLE001
                pass
    timeline.sort(key=lambda e: (e.date, e.label))
    # Phase first (in the order phases appear along the calendar), then by
    # start, so a Gantt reads top-left to bottom-right without re-sorting.
    _phase_first_seen: dict[str, str] = {}
    for row in ablaufplan:
        anchor = row.start or row.end
        if row.phase not in _phase_first_seen or anchor < _phase_first_seen[row.phase]:
            _phase_first_seen[row.phase] = anchor
    ablaufplan.sort(
        key=lambda r: (
            _phase_first_seen.get(r.phase, "9999-99-99"),
            r.phase,
            r.start or r.end,
            r.title,
        )
    )

    # Risks from registry (confidential risks excluded via export_public())
    risks: list[RiskRow] = []
    try:
        from hermes_assistant.risks.registry import RiskRegistry as _RiskRegistry
        _rr: Any = (
            risk_registry if risk_registry is not None
            else _RiskRegistry(Path(settings.data_dir) / "risks.db")
        )
        for r in _rr.export_public():
            sev_w = _SEVERITY_WEIGHT.get(r.severity.value, 2)
            risks.append(RiskRow(
                id=r.id,
                title=r.title,
                severity=r.severity.value,
                likelihood=r.likelihood,
                status=r.status.value,
                score=sev_w * r.likelihood,
                updated_at=r.updated_at,
            ))
    except Exception:  # noqa: BLE001
        pass

    # Reviews from job store
    reviews: list[ReviewSummaryRow] = []
    try:
        from hermes_assistant.hermes.model import ReviewResult as _ReviewResult
        for job in _js.list(JobStatus.done):
            if job.result_json:
                try:
                    rr = _ReviewResult.model_validate_json(job.result_json)
                    reviews.append(ReviewSummaryRow(
                        job_id=job.id, rubric_id=rr.rubric_id, verdict=rr.verdict.value,
                        blockers=rr.blockers, majors=rr.majors, minors=rr.minors,
                        deliverable=Path(job.deliverable_path).name,
                    ))
                except Exception:  # noqa: BLE001
                    pass
    except Exception:  # noqa: BLE001
        pass

    projects = []
    if _root.is_dir():
        for d in sorted(_root.iterdir()):
            if d.is_dir():
                projects.append(ProjectSummary(project_id=d.name))

    scope = esc(project_id) if project_id else "all projects"
    range_start = timeline[0].date if timeline else today_str
    range_end = timeline[-1].date if timeline else today_str
    return DashboardData(
        generated_at=_now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        scope=scope, range_start=range_start, range_end=range_end,
        projects=projects, timeline=timeline, kanban=kanban, wbs=wbs,
        pendenzen=pend_rows, reviews=reviews, risks=risks,
        ablaufplan=ablaufplan, decisions=decisions,
    )


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def _render_timeline(entries: list[TimelineEntry]) -> str:
    if not entries:
        return "<p>No timeline items found. Run <code>hermes schedule</code> to derive one.</p>"
    parts = ['<ul class="tl-list">']
    for e in entries:
        parts.append(
            f'<li class="tl-item">'
            f'<span class="tl-date">{esc(e.date)}</span>'
            f'<span class="tl-dot {esc(e.status)}" aria-hidden="true"></span>'
            f'<span>{esc(e.label)}</span>'
            f'<small class="meta">[{esc(e.kind)}]</small>'
            f'</li>'
        )
    parts.append("</ul>")
    return "\n".join(parts)


def _render_kanban(columns: list[KanbanColumn]) -> str:
    parts = ['<div class="kanban-grid">']
    for col in columns:
        count = len(col.cards) + col.overflow
        parts.append(f'<div class="k-col"><div class="k-hdr">{esc(col.label)} <span>({count})</span></div>')
        for card in col.cards:
            parts.append(
                f'<div class="k-card">'
                f'<span style="color:#999;font-size:.75rem">{esc(card.wbs_number)}</span> {esc(card.title)}'
                f'<div class="k-meta">{esc(card.owner) or "&ndash;"}</div>'
                f'</div>'
            )
        if col.overflow:
            parts.append(f'<div class="k-card" style="color:#999;font-style:italic">+{col.overflow} more</div>')
        if not col.cards and not col.overflow:
            parts.append('<div class="k-card" style="color:#bbb;font-style:italic">Empty</div>')
        parts.append("</div>")
    parts.append("</div>")
    return "\n".join(parts)


def _render_pendenzen(rows: list[PendenzRow]) -> str:
    if not rows:
        return "<p>No pendenzen found.</p>"
    sources = sorted({r.source for r in rows})
    opts_src = "".join(f'<option value="{esc(s)}">{esc(s)}</option>' for s in sources)
    opts_prio = "".join(f'<option value="{p}">{p}</option>' for p in ("blocker", "high", "medium", "low"))
    header = "".join(f'<th><button data-sort-col="{i}">{h}</button></th>' for i, h in enumerate(("Title", "Source", "Priority", "Status", "Owner", "Due", "Ref")))
    tbody_parts = []
    for r in rows:
        cls = f" prio-{r.priority}" if r.priority in ("blocker", "high") else ""
        tbody_parts.append(
            f'<tr class="{cls.strip()}">'
            f'<td>{esc(r.title)}</td><td>{esc(r.source)}</td><td>{esc(r.priority)}</td>'
            f'<td>{esc(r.status)}</td><td>{esc(r.owner)}</td>'
            f'<td>{esc(r.due_date)}</td><td>{esc(r.source_ref)}</td></tr>'
        )
    return (
        f'<div class="filters">'
        f'<select data-filter-col="1" onchange="applyFilters(\'pend-table\')">'
        f'<option value="">All sources</option>{opts_src}</select>'
        f'<select data-filter-col="2" onchange="applyFilters(\'pend-table\')">'
        f'<option value="">All priorities</option>{opts_prio}</select>'
        f'<button onclick="exportTableCSV(\'pend-table\')">Export CSV</button>'
        f'</div>'
        f'<div class="tbl-wrap"><table id="pend-table">'
        f'<thead><tr>{header}</tr></thead>'
        f'<tbody>{"".join(tbody_parts)}</tbody></table></div>'
    )


def _render_wbs(nodes: list[WBSNode]) -> str:
    def _node_html(n: WBSNode) -> str:
        label = (
            f'<span class="wbs-num">{esc(n.wbs_number)}</span>'
            f' {esc(n.title)}'
            f' <small class="meta">[{esc(n.kind)}/{esc(n.status)}]</small>'
            f'{(" " + esc(n.owner)) if n.owner else ""}'
        )
        if n.children:
            inner = "".join(_node_html(c) for c in n.children)
            return f"<details><summary>{label}</summary>{inner}</details>"
        return f'<div class="wbs-leaf">{label}</div>'

    if not nodes:
        return "<p>No tasks. Use <code>hermes task-add</code> to create tasks.</p>"
    body = "".join(_node_html(n) for n in nodes)
    btns = '<div class="wbs-btn"><button onclick="setAllDetails(true)">Expand all</button><button onclick="setAllDetails(false)">Collapse all</button></div>'
    return btns + body


def _render_reviews(rows: list[ReviewSummaryRow]) -> str:
    if not rows:
        return "<p>No completed reviews. Use <code>hermes review --wait</code> to run one.</p>"
    header = "".join(f'<th><button data-sort-col="{i}">{h}</button></th>' for i, h in enumerate(("Job", "Rubric", "Verdict", "Blockers", "Majors", "Minors", "Deliverable")))
    tbody_parts = []
    for r in rows:
        vc = "v-pass" if r.verdict == "pass" else ("v-partial" if "comment" in r.verdict else "v-fail")
        tbody_parts.append(
            f'<tr><td><code>{esc(r.job_id[:12])}</code></td><td>{esc(r.rubric_id)}</td>'
            f'<td><span class="{vc}">{esc(r.verdict)}</span></td>'
            f'<td>{r.blockers}</td><td>{r.majors}</td><td>{r.minors}</td>'
            f'<td>{esc(r.deliverable)}</td></tr>'
        )
    return (
        f'<div class="tbl-wrap"><table id="reviews-table">'
        f'<thead><tr>{header}</tr></thead>'
        f'<tbody>{"".join(tbody_parts)}</tbody></table></div>'
    )


def _render_embedded_json(data: DashboardData) -> str:
    """Serialize DashboardData to JSON, escaping end-tags to prevent XSS."""
    raw = data.model_dump_json()
    return raw.replace("</", "<\\/")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_safe_export(data: DashboardData, rendered_html: str) -> list[str]:
    """Return a list of violation strings (empty = clean)."""
    violations: list[str] = []
    lower = rendered_html.lower()
    for field in _FORBIDDEN_FIELDS:
        if field in lower:
            violations.append(f"Forbidden field name {field!r} found in rendered HTML")
    for kw in _CONFIDENTIAL_KEYWORDS:
        if kw in lower:
            violations.append(f"Confidential keyword {kw!r} found in rendered HTML")
    if _FS_RE.search(rendered_html):
        violations.append("Absolute filesystem path found in rendered HTML")
    if _EXT_URL_RE.search(rendered_html):
        violations.append("External URL found in rendered HTML")
    return violations


def render_html(data: DashboardData) -> str:
    """Render DashboardData to a self-contained HTML string.

    Raises ConfidentialityError if validate_safe_export finds violations.
    """
    scope = esc(data.scope)
    page = _PAGE.substitute(
        title=f"HERMES Dashboard — {scope}",
        css=_CSS,
        scope=scope,
        range_start=esc(data.range_start),
        range_end=esc(data.range_end),
        timeline=_render_timeline(data.timeline),
        kanban=_render_kanban(data.kanban),
        pendenzen=_render_pendenzen(data.pendenzen),
        wbs=_render_wbs(data.wbs),
        reviews=_render_reviews(data.reviews),
        footer=f"Generated {esc(data.generated_at)} · HERMES Local Assistant",
        embedded_json=_render_embedded_json(data),
        js=_JS,
    )
    violations = validate_safe_export(data, page)
    if violations:
        raise ConfidentialityError(violations)
    return page
