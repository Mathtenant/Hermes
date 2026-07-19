"""CLI entrypoint (Typer)."""

import json
from collections import Counter
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from hermes_assistant.agents import panel_eval as panel_eval_module
from hermes_assistant.agents.consistency import ConsistencyError, check_consistency
from hermes_assistant.agents.redteam import run_premortem
from hermes_assistant.calibration.loader import CalibrationDataError, load_gold
from hermes_assistant.config import settings
from hermes_assistant.hermes.intake import run_intake
from hermes_assistant.hermes.model import IntakeResult, ProjectPlan, ReviewResult, Verdict
from hermes_assistant.hermes.planner import build_plan, check_plan
from hermes_assistant.hermes.project_types import load_project_type
from hermes_assistant.hermes.scribe import ScribeError, safe_project_dir, write_artifacts
from hermes_assistant.jobqueue.jobs import Job, JobStatus, JobStore
from hermes_assistant.jobqueue.worker import Worker
from hermes_assistant.llm.client import OllamaClient
from hermes_assistant.llm.roster import ROSTER
from hermes_assistant.rag.ingest import IngestStatus, ingest_path
from hermes_assistant.rag.store import ChromaStore
from hermes_assistant.rubrics.loader import RubricError, default_rubric_id, load_rubric
from hermes_assistant.scheduling.deadlines import cross_project_view
from hermes_assistant.scheduling.derive import CyclicDependencyError, derive_schedule
from hermes_assistant.scheduling.ics import to_ics
from hermes_assistant.scheduling.model import Schedule
from hermes_assistant.tasks.meetings import MeetingNote, MeetingStore
from hermes_assistant.tasks.model import Task
from hermes_assistant.tasks.pendenzen import Pendenz, PendenzSource
from hermes_assistant.tasks.store import TaskStore


def _store() -> ChromaStore:
    """Open the corpus ChromaStore from configured settings."""
    return ChromaStore(settings.vectorstore_path, settings.rag_collection_name)


def _client() -> OllamaClient:
    """Build an OllamaClient from configured settings."""
    return OllamaClient(host=settings.ollama_host, num_thread=settings.ollama_num_thread)


def _job_store() -> JobStore:
    """Open the SQLite job store from configured settings."""
    return JobStore(settings.queue_db_path)

app = typer.Typer(help="HERMES Local Assistant — senior-level project management")
console = Console()


@app.command()
def init() -> None:
    """Create local data directories (vectorstore, projects, traces)."""
    targets = [
        Path(settings.vectorstore_path),
        Path(settings.projects_path),
        Path(settings.traces_path).parent,
    ]
    for target in targets:
        target.mkdir(parents=True, exist_ok=True)
        console.print(f"[green]ok[/green] {target}")
    console.print(
        f"[bold]Ollama host:[/bold] {settings.ollama_host} "
        f"(threads={settings.ollama_num_thread})"
    )


@app.command()
def models() -> None:
    """List the model roster and whether each is pulled in local Ollama."""
    client = OllamaClient(host=settings.ollama_host)
    health = client.health()
    installed = set(health["models"]) if health["available"] else set()

    table = Table(title="HERMES model roster")
    table.add_column("role")
    table.add_column("model id")
    table.add_column("mode")
    table.add_column("status")
    for role, cfg in ROSTER.items():
        if not health["available"]:
            status = "[yellow]ollama offline[/yellow]"
        elif cfg.id in installed:
            status = "[green]pulled[/green]"
        else:
            status = "[red]missing[/red]"
        table.add_row(role.value, cfg.id, cfg.mode.value, status)

    console.print(table)
    if not health["available"]:
        console.print(f"[yellow]Ollama unreachable at {settings.ollama_host}[/yellow]")


@app.command()
def ingest(
    path: str,
    project: str = typer.Option(
        "", "--project", "-p", help="Tag every chunk with this project for filtering."
    ),
) -> None:
    """Add a file or directory of documents to the local vector store.

    Ingestion is idempotent: re-running on unchanged files adds nothing;
    edited files have their stale chunks replaced.
    """
    store = _store()
    report = ingest_path(store, _client(), path, project=project or None)

    table = Table(title=f"Ingest report — {path}")
    table.add_column("file")
    table.add_column("status")
    table.add_column("chunks", justify="right")
    _colors = {
        IngestStatus.ADDED: "green",
        IngestStatus.UPDATED: "cyan",
        IngestStatus.SKIPPED: "yellow",
        IngestStatus.EMPTY: "yellow",
        IngestStatus.FAILED: "red",
    }
    for result in report.results:
        color = _colors.get(result.status, "white")
        name = Path(result.source).name
        detail = f" ({result.error})" if result.error else ""
        table.add_row(
            f"{name}{detail}",
            f"[{color}]{result.status.value}[/{color}]",
            str(result.chunks),
        )
    console.print(table)
    console.print(
        f"[bold]added[/bold] {report.files_added}  "
        f"[bold]updated[/bold] {report.files_updated}  "
        f"[bold]skipped[/bold] {report.files_skipped}  "
        f"[bold]failed[/bold] {report.files_failed}  "
        f"[bold]chunks[/bold] {report.chunks_added}  "
        f"[bold]total in store[/bold] {store.count()}"
    )
    if report.files_failed:
        raise typer.Exit(code=1)


@app.command()
def show(identifier: str) -> None:
    """Show a chunk by its ID, or list all chunks from a source file.

    ``identifier`` is tried first as a chunk ID, then as a source path
    (both as-given and resolved to an absolute path).
    """
    store = _store()

    chunk = store.get_by_id(identifier)
    if chunk is not None:
        console.print(f"[bold]chunk[/bold] {chunk.id}")
        console.print(f"[bold]source[/bold] {chunk.metadata.get('source', '')}")
        console.print(f"[bold]heading[/bold] {chunk.metadata.get('heading') or '-'}")
        console.print(f"[bold]tokens[/bold] {chunk.metadata.get('token_count', '?')}")
        console.print("[bold]text[/bold]")
        console.print(chunk.text)
        return

    candidates = [identifier, str(Path(identifier).resolve())]
    for source in candidates:
        chunks = store.get_by_source(source)
        if chunks:
            table = Table(title=f"Chunks from {Path(source).name}")
            table.add_column("chunk id")
            table.add_column("heading")
            table.add_column("tokens", justify="right")
            for stored in sorted(
                chunks, key=lambda c: int(c.metadata.get("chunk_index", 0))
            ):
                table.add_row(
                    stored.id,
                    str(stored.metadata.get("heading") or "-"),
                    str(stored.metadata.get("token_count", "?")),
                )
            console.print(table)
            return

    console.print(f"[red]not found[/red] no chunk or source matching {identifier!r}")
    raise typer.Exit(code=1)


def _online_client() -> OllamaClient | None:
    """Return a client only if the local Ollama service is reachable."""
    client = _client()
    try:
        if client.health().get("available"):
            return client
    except Exception:  # noqa: BLE001 — offline is a valid state, degrade quietly
        pass
    return None


def _read_description(description: str) -> str:
    """Treat ``description`` as a file path if it exists, else as literal text."""
    path = Path(description)
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return description


@app.command()
def intake(
    description: str = typer.Argument(..., help="Description text, or a path to a .txt file."),
    project: str = typer.Option(..., "--project", "-p", help="Stable project id."),
    project_type: str = typer.Option("", "--type", "-t", help="Force a project type."),
    interactive: bool = typer.Option(False, "--interactive/--no-interactive"),
) -> None:
    """Run the Socratic intake interview and write intake.json.

    The router (if Ollama is reachable) classifies the type and extracts
    pre-answered fields; missing fields are prompted only with --interactive.
    """
    try:
        project_dir = safe_project_dir(settings.projects_path, project)
    except ScribeError as exc:
        console.print(f"[red]error[/red] {exc}")
        raise typer.Exit(code=1) from exc
    result = run_intake(
        _read_description(description),
        project,
        interactive=interactive,
        client=_online_client(),
        project_type=project_type or None,
    )
    project_dir.mkdir(parents=True, exist_ok=True)
    out = project_dir / "intake.json"
    out.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    console.print(f"[green]ok[/green] intake -> {out}")
    console.print(f"[bold]type[/bold] {result.project_type}  "
                  f"[bold]objectives[/bold] {len(result.objectives)}  "
                  f"[bold]sizing flags[/bold] {sum(result.sizing_flags.values())}")


@app.command()
def plan(
    description: str = typer.Argument("", help="Description text or .txt path (omit if --intake)."),
    project: str = typer.Option("", "--project", "-p", help="Stable project id."),
    intake_file: str = typer.Option("", "--intake", help="Path to an existing intake.json."),
    project_type: str = typer.Option("", "--type", "-t", help="Force a project type."),
) -> None:
    """Generate a HERMES ProjectPlan (skeleton + best-effort enrichment).

    Provide either a description (runs intake first) or --intake with a prebuilt
    intake.json. Writes intake.json, plan.json, plan.md and decisions.md.
    """
    if intake_file:
        result = IntakeResult.model_validate_json(Path(intake_file).read_text(encoding="utf-8"))
    elif description and project:
        result = run_intake(
            _read_description(description),
            project,
            client=_online_client(),
            project_type=project_type or None,
        )
    else:
        console.print("[red]error[/red] provide --intake PATH, or a description plus --project")
        raise typer.Exit(code=1)

    pt = load_project_type(result.project_type)
    plan_obj = build_plan(result, pt, client=_online_client())
    report = check_plan(plan_obj, pt, result)
    paths = write_artifacts(settings.projects_path, result, plan_obj, flags=report.flags)

    outcomes = [oc.id for ph in plan_obj.phases for oc in ph.outcomes]
    console.print(f"[green]ok[/green] plan -> {paths['plan']}")
    console.print(f"[bold]phases[/bold] {len(plan_obj.phases)}  "
                  f"[bold]outcomes[/bold] {len(outcomes)}  "
                  f"[bold]roles[/bold] {', '.join(plan_obj.roles)}")


@app.command(name="check-plan")
def check_plan_cmd(
    plan_file: str = typer.Argument(..., help="Path to plan.json."),
    intake_file: str = typer.Option(..., "--intake", help="Path to intake.json."),
) -> None:
    """Deterministically flag missing mandatory outcomes & unassigned roles.

    Exits non-zero if any flags are raised.
    """
    plan_obj = ProjectPlan.model_validate_json(Path(plan_file).read_text(encoding="utf-8"))
    result = IntakeResult.model_validate_json(Path(intake_file).read_text(encoding="utf-8"))
    pt = load_project_type(result.project_type)
    report = check_plan(plan_obj, pt, result)

    if report.ok:
        console.print("[green]ok[/green] plan is complete — no flags")
        return
    table = Table(title=f"check-plan — {report.project_id}")
    table.add_column("kind")
    table.add_column("severity")
    table.add_column("detail")
    for flag in report.flags:
        table.add_row(flag.kind, flag.severity.value, flag.detail)
    console.print(table)
    console.print(f"[red]{len(report.flags)} flag(s)[/red]")
    raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# Phase 3 — rubric critic & async job queue
# --------------------------------------------------------------------------- #
_VERDICT_COLOR = {
    Verdict.pass_: "green",
    Verdict.pass_with_comments: "yellow",
    Verdict.fail: "red",
}


def _render_review(result: ReviewResult) -> None:
    """Pretty-print a ReviewResult: verdict banner + per-finding table."""
    color = _VERDICT_COLOR.get(result.verdict, "white")
    console.print(
        f"[bold {color}]verdict: {result.verdict.value}[/bold {color}]  "
        f"blockers={result.blockers} majors={result.majors} minors={result.minors}"
    )
    console.print(f"[dim]{result.verdict_rationale}[/dim]")

    table = Table(title=f"{result.rubric_id} v{result.rubric_version} — findings")
    table.add_column("criterion")
    table.add_column("dim")
    table.add_column("result")
    table.add_column("sev")
    table.add_column("conf", justify="right")
    table.add_column("evidence")
    for f in result.findings:
        rc = {"pass": "green", "partial": "yellow", "fail": "red"}.get(f.result, "white")
        evidence = f.evidence_quote if f.result != "pass" else ""
        if len(evidence) > 48:
            evidence = evidence[:45] + "..."
        table.add_row(
            f.criterion_id,
            f.dimension,
            f"[{rc}]{f.result}[/{rc}]",
            f.severity.value if f.severity else "-",
            f"{f.confidence:.2f}",
            evidence,
        )
    console.print(table)


@app.command()
def review(
    file: str = typer.Argument(..., help="Path to the deliverable to review."),
    rubric: str = typer.Option("", "--rubric", "-r", help="Rubric id (default: seed rubric)."),
    samples: int = typer.Option(
        0, "--samples", "-n", help="Self-consistency samples (default: config)."
    ),
    wait: bool = typer.Option(
        False, "--wait", "-w", help="Process inline now instead of just enqueuing."
    ),
    panel: bool = typer.Option(
        False,
        "--panel/--no-panel",
        help=(
            "Use multiple diverse models (experimental, must outperform "
            "single-judge on gold set)."
        ),
    ),
) -> None:
    """Enqueue (or, with --wait, run) a rubric review of a deliverable.

    Without --wait the review is queued for a worker; the job id is printed.
    Exit code is non-zero when a completed review's verdict is 'fail'.
    """
    path = Path(file)
    if not path.is_file():
        console.print(f"[red]error[/red] file not found: {file}")
        raise typer.Exit(code=2)

    rubric_id = rubric or default_rubric_id()
    try:
        loaded = load_rubric(rubric_id)
    except RubricError as exc:
        console.print(f"[red]error[/red] {exc}")
        raise typer.Exit(code=2) from exc

    n_samples = samples or settings.critic_samples
    store = _job_store()
    job = store.enqueue(
        str(path),
        loaded.rubric_id,
        rubric_version=loaded.version,
        samples=n_samples,
        panel=panel,
    )
    console.print(
        f"[green]queued[/green] job [bold]{job.id[:12]}[/bold] "
        f"review of {path.name} with {rubric_id} v{loaded.version} (n={n_samples})"
    )

    if not wait:
        console.print("[dim]run 'hermes worker --once' to process, then "
                      f"'hermes job {job.id[:12]}'[/dim]")
        return

    Worker(store).run(once=True)
    done = store.get(job.id)
    if done is None or done.status != JobStatus.done or done.result_json is None:
        err = done.error if done else "job vanished"
        console.print(f"[red]failed[/red] {err}")
        raise typer.Exit(code=2)
    result = ReviewResult.model_validate_json(done.result_json)
    _render_review(result)
    if result.verdict == Verdict.fail:
        raise typer.Exit(code=1)


@app.command()
def jobs(
    status: str = typer.Option("", "--status", "-s", help="Filter by status."),
) -> None:
    """List queued/finished jobs, newest first."""
    store = _job_store()
    filt = JobStatus(status) if status else None
    rows = store.list(filt)
    if not rows:
        console.print("[yellow]no jobs[/yellow]")
        return
    table = Table(title="jobs")
    table.add_column("id")
    table.add_column("kind")
    table.add_column("status")
    table.add_column("rubric")
    table.add_column("attempts", justify="right")
    table.add_column("deliverable")
    _sc = {
        JobStatus.pending: "yellow",
        JobStatus.running: "cyan",
        JobStatus.done: "green",
        JobStatus.failed: "red",
    }
    for j in rows:
        color = _sc.get(j.status, "white")
        table.add_row(
            j.id[:12],
            j.kind,
            f"[{color}]{j.status.value}[/{color}]",
            j.rubric_id,
            f"{j.attempts}/{j.max_attempts}",
            Path(j.deliverable_path).name,
        )
    console.print(table)


@app.command()
def job(job_id: str = typer.Argument(..., help="Job id or unique prefix.")) -> None:
    """Show one job and its stored ReviewResult (exit 1 if verdict is fail)."""
    store = _job_store()
    found: Job | None = store.get(job_id)
    if found is None:
        console.print(f"[red]not found[/red] no job matching {job_id!r}")
        raise typer.Exit(code=2)

    console.print(f"[bold]job[/bold] {found.id}")
    console.print(f"[bold]status[/bold] {found.status.value}  "
                  f"[bold]attempts[/bold] {found.attempts}/{found.max_attempts}")
    console.print(f"[bold]deliverable[/bold] {found.deliverable_path}")
    console.print(f"[bold]rubric[/bold] {found.rubric_id} v{found.rubric_version}")
    if found.error:
        console.print(f"[red]error[/red] {found.error}")
    if found.result_json is None:
        return
    result = ReviewResult.model_validate_json(found.result_json)
    _render_review(result)
    if result.verdict == Verdict.fail:
        raise typer.Exit(code=1)


@app.command()
def worker(
    once: bool = typer.Option(
        False, "--once", help="Drain the queue once and exit (else run forever)."
    ),
) -> None:
    """Run the review worker: claim pending jobs, run the critic, store results."""
    store = _job_store()
    w = Worker(store)
    w.install_signal_handlers()
    processed = w.run(once=once)
    console.print(f"[green]worker[/green] processed {processed} job(s)")


# --------------------------------------------------------------------------- #
# Phase 3.5 — Scheduling & ICS export (§24–30)
# --------------------------------------------------------------------------- #

@app.command()
def schedule(
    plan_id: str = typer.Argument(..., help="Project id (folder name under projects_path)."),
    start: str = typer.Option("", "--start", "-s", help="Start date YYYY-MM-DD."),
    deadline: str = typer.Option("", "--deadline", "-d", help="Hard deadline YYYY-MM-DD."),
    label: str = typer.Option("", "--label", help="Human-readable project label for ICS CATEGORIES."),
    no_holidays: bool = typer.Option(False, "--no-holidays", help="Skip Zürich holidays (weekdays only)."),
) -> None:
    """Derive a dated schedule from a project plan and save schedule.json.

    Reads ``plan.json`` from ``projects/{plan_id}/``, runs the deterministic
    dependency-dating algorithm, and writes ``schedule.json`` alongside it.
    Any items that cannot fit before the deadline are printed as warnings.
    """
    from datetime import date as _date

    project_dir = Path(settings.projects_path) / plan_id
    plan_file = project_dir / "plan.json"
    if not plan_file.is_file():
        console.print(f"[red]error[/red] plan not found: {plan_file}")
        raise typer.Exit(code=2)

    plan_obj = ProjectPlan.model_validate_json(plan_file.read_text(encoding="utf-8"))

    start_date: _date
    if start:
        try:
            start_date = _date.fromisoformat(start)
        except ValueError:
            console.print(f"[red]error[/red] invalid start date: {start!r} (expected YYYY-MM-DD)")
            raise typer.Exit(code=2)
    else:
        start_date = _date.today()

    dl: _date | None = None
    if deadline:
        try:
            dl = _date.fromisoformat(deadline)
        except ValueError:
            console.print(f"[red]error[/red] invalid deadline: {deadline!r} (expected YYYY-MM-DD)")
            raise typer.Exit(code=2)

    project_label = label or plan_id

    try:
        sched = derive_schedule(
            plan_obj,
            project_id=plan_id,
            project_label=project_label,
            start_date=start_date,
            deadline=dl,
            use_zurich_holidays=not no_holidays,
        )
    except CyclicDependencyError as exc:
        console.print(f"[red]error[/red] dependency cycle: {exc}")
        raise typer.Exit(code=2) from exc

    out = project_dir / "schedule.json"
    out.write_text(sched.model_dump_json(indent=2), encoding="utf-8")
    console.print(f"[green]ok[/green] schedule -> {out}  ({len(sched.items)} items)")

    if sched.negative_float:
        console.print(
            f"[red]warning[/red] {len(sched.negative_float)} item(s) cannot fit before "
            f"the deadline ({deadline}):"
        )
        for item_id in sched.negative_float:
            matching = next((it for it in sched.items if it.item_id == item_id), None)
            name = matching.title if matching else item_id
            console.print(f"  [red]negative float[/red] {item_id}: {name}")
    else:
        console.print("[green]ok[/green] no negative-float items — all fit within the deadline")


@app.command()
def deadlines(
    all_projects: bool = typer.Option(False, "--all", "-a", help="Show all projects."),
    within: int = typer.Option(14, "--in", help="Look-ahead window in calendar days."),
) -> None:
    """Show cross-project upcoming deadlines, collisions, and overdue items.

    Reads ``schedule.json`` from every project directory and aggregates them
    into a single deadline view, surfacing same-day collisions across projects.
    """
    projects_root = Path(settings.projects_path)
    if not projects_root.is_dir():
        console.print(f"[red]error[/red] projects directory not found: {projects_root}")
        raise typer.Exit(code=2)

    schedules: list[Schedule] = []
    for project_dir in sorted(projects_root.iterdir()):
        if not project_dir.is_dir():
            continue
        sched_file = project_dir / "schedule.json"
        if not sched_file.is_file():
            if all_projects:
                console.print(f"[yellow]skip[/yellow] {project_dir.name}: no schedule.json")
            continue
        try:
            schedules.append(Schedule.model_validate_json(sched_file.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]error[/red] {sched_file}: {exc}")

    if not schedules:
        console.print("[yellow]no schedules found[/yellow]")
        return

    view = cross_project_view(schedules, within_days=within)

    if view.overdue:
        table = Table(title=f"Overdue ({len(view.overdue)})", style="red")
        table.add_column("project")
        table.add_column("item")
        table.add_column("due")
        for it in view.overdue:
            table.add_row(it.project_id, it.title, str(it.due))
        console.print(table)

    if view.upcoming:
        table = Table(title=f"Upcoming — next {within} days ({len(view.upcoming)})")
        table.add_column("project")
        table.add_column("item")
        table.add_column("kind")
        table.add_column("due")
        for it in view.upcoming:
            table.add_row(it.project_id, it.title, it.kind.value, str(it.due))
        console.print(table)
    else:
        console.print(f"[green]nothing due in the next {within} days[/green]")

    if view.collisions:
        console.print(f"[red]warning[/red] {len(view.collisions)} same-day collision(s) across projects:")
        for uid_a, uid_b in view.collisions:
            console.print(f"  [red]collision[/red] {uid_a}  vs  {uid_b}")


@app.command()
def ics(
    plan_id: str = typer.Argument(..., help="Project id (folder name under projects_path)."),
    tasks_as: str = typer.Option(
        "events", "--tasks-as",
        help="'events' (Outlook-safe default) or 'vtodo' (Apple/Thunderbird)."
    ),
    output: str = typer.Option("", "--output", "-o", help="Override output file path."),
) -> None:
    """Export a project schedule to a RFC-5545 ICS calendar file.

    Reads ``schedule.json`` from ``projects/{plan_id}/`` and emits an ``.ics``
    file alongside it (or at the path given by --output). The file can be
    imported directly into Outlook / Apple Calendar / Thunderbird.

    By default tasks are emitted as all-day VEVENT entries with VALARM
    reminders (Outlook-safe). Use ``--tasks-as vtodo`` for VTODO components.
    """
    if tasks_as not in ("events", "vtodo"):
        console.print(f"[red]error[/red] --tasks-as must be 'events' or 'vtodo', got {tasks_as!r}")
        raise typer.Exit(code=2)

    project_dir = Path(settings.projects_path) / plan_id
    sched_file = project_dir / "schedule.json"
    if not sched_file.is_file():
        console.print(f"[red]error[/red] schedule not found: {sched_file}")
        console.print("[dim]run 'hermes schedule' first[/dim]")
        raise typer.Exit(code=2)

    sched = Schedule.model_validate_json(sched_file.read_text(encoding="utf-8"))
    files = to_ics(sched, tasks_as=tasks_as, merged=True)

    for filename, content in files.items():
        dest = Path(output) if output else project_dir / filename
        dest.write_text(content, encoding="utf-8")
        console.print(f"[green]ok[/green] ICS -> {dest}  ({len(sched.items)} components)")

    if sched.negative_float:
        console.print(
            f"[yellow]note[/yellow] {len(sched.negative_float)} negative-float item(s) "
            "are included in the ICS but exceed the original deadline"
        )


@app.command()
def calibrate(
    rubric_id: str = typer.Argument(..., help="Rubric id whose gold set to inspect."),
    base_dir: str = typer.Option("", "--base-dir", help="Override calibration data directory."),
) -> None:
    """Show the human gold set for a rubric (label distribution per criterion).

    Loads ``{rubric_id}.gold.yaml`` from the configured calibration_path (or
    --base-dir) and prints a per-criterion label-count table. Useful for
    verifying that a gold set is complete before running a full calibration.
    """
    try:
        gold = load_gold(rubric_id, base_dir=base_dir or None)
    except CalibrationDataError as exc:
        console.print(f"[red]error[/red] {exc}")
        raise typer.Exit(code=2) from exc

    by_criterion: dict[str, Counter[str]] = {}
    for label in gold:
        by_criterion.setdefault(label.criterion_id, Counter())[label.human_result] += 1
    items = len({g.item_id for g in gold})

    table = Table(title=f"Gold set — {rubric_id}  ({items} items, {len(gold)} labels)")
    table.add_column("criterion")
    table.add_column("pass", justify="right")
    table.add_column("partial", justify="right")
    table.add_column("fail", justify="right")
    table.add_column("total", justify="right")
    for criterion_id, counts in sorted(by_criterion.items()):
        table.add_row(
            criterion_id,
            str(counts["pass"]),
            str(counts["partial"]),
            str(counts["fail"]),
            str(sum(counts.values())),
        )
    console.print(table)
    console.print(f"[bold]items[/bold] {items}  [bold]total labels[/bold] {len(gold)}")


# --------------------------------------------------------------------------- #
# Phase 4 — pre-mortem & consistency agents
# --------------------------------------------------------------------------- #

@app.command()
def premortem(
    plan_id: str = typer.Argument(..., help="Project id (folder name under projects_path)."),
    prompt: str = typer.Option("", "--prompt", help="Override the user prompt sent to the model."),
) -> None:
    """Run a pre-mortem failure analysis on a project plan.

    Reads ``plan.json`` from ``projects/{plan_id}/``, calls the critic model
    to enumerate likely failure scenarios, and writes ``premortem.json``
    alongside the plan.  Gracefully degrades to an empty result when the model
    is unavailable.
    """
    project_dir = Path(settings.projects_path) / plan_id
    plan_file = project_dir / "plan.json"
    if not plan_file.is_file():
        console.print(f"[red]error[/red] plan not found: {plan_file}")
        raise typer.Exit(code=2)

    plan_obj = ProjectPlan.model_validate_json(plan_file.read_text(encoding="utf-8"))
    result = run_premortem(
        plan_obj,
        prompt_override=prompt or None,
        client=_online_client(),
    )

    if not result.risks:
        console.print(
            "[yellow]pre-mortem: no failure scenarios generated "
            "(model unavailable or plan has no identifiable risks)[/yellow]"
        )
        return

    table = Table(title=f"Pre-mortem — {plan_id} ({len(result.risks)} scenarios)")
    table.add_column("description")
    table.add_column("likelihood")
    table.add_column("impact")
    table.add_column("owner")
    table.add_column("mitigation")
    for risk in result.risks:
        table.add_row(
            risk.description,
            risk.likelihood,
            risk.impact,
            risk.owner,
            risk.mitigation,
        )
    console.print(table)

    out = project_dir / "premortem.json"
    out.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    console.print(f"[green]ok[/green] pre-mortem -> {out}")


@app.command(name="consistency-check")
def consistency_check_cmd(
    plan_id: str = typer.Argument(..., help="Project id (folder name under projects_path)."),
) -> None:
    """Run MECE and consistency checks on a project plan (deterministic, no LLM).

    Reads ``plan.json`` from ``projects/{plan_id}/``, checks for MECE violations,
    invalid effort values, and cross-section reference errors.  Exits non-zero
    and prints every violation if any are found.
    """
    project_dir = Path(settings.projects_path) / plan_id
    plan_file = project_dir / "plan.json"
    if not plan_file.is_file():
        console.print(f"[red]error[/red] plan not found: {plan_file}")
        raise typer.Exit(code=2)

    plan_obj = ProjectPlan.model_validate_json(plan_file.read_text(encoding="utf-8"))

    try:
        check_consistency(plan_obj)
        console.print(f"[green]ok[/green] no consistency violations found in {plan_id}")
    except ConsistencyError as exc:
        table = Table(title=f"Consistency violations — {plan_id} ({len(exc.violations)})")
        table.add_column("violation")
        for v in exc.violations:
            table.add_row(v)
        console.print(table)
        console.print(f"[red]{len(exc.violations)} violation(s)[/red]")
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# Phase 5 — panel evaluation (§P5d)
# --------------------------------------------------------------------------- #

@app.command(name="panel-eval")
def panel_eval(
    rubric_id: str = typer.Argument(..., help="Rubric ID from calibration/ data."),
    single_results_json: str = typer.Option(
        ...,
        "--single-results",
        help="JSON file mapping 'item_id|criterion_id' keys to pass/partial/fail results.",
    ),
    panel_results_json: str = typer.Option(
        ...,
        "--panel-results",
        help="JSON file mapping 'item_id|criterion_id' keys to pass/partial/fail results.",
    ),
    base_dir: str = typer.Option(
        "", "--base-dir", help="Override calibration data directory."
    ),
) -> None:
    """Evaluate panel vs single-judge on gold set. Panel must beat single-judge on κ.

    Both result JSON files must use the key format ``'item_id|criterion_id'``
    with values ``pass``, ``partial``, or ``fail``.

    Exits with code 0 if the panel beats the single judge (delta κ > 0);
    exits with code 1 if the single judge wins or they tie (pessimistic).
    """
    try:
        gold = load_gold(rubric_id, base_dir=base_dir or None)
    except CalibrationDataError as exc:
        console.print(f"[red]error[/red] {exc}")
        raise typer.Exit(code=2) from exc

    def _load_results(
        path: str,
    ) -> dict[tuple[str, str], panel_eval_module._ResultStr]:
        p = Path(path)
        if not p.is_file():
            console.print(f"[red]error[/red] results file not found: {path}")
            raise typer.Exit(code=2)
        raw: dict[str, str] = json.loads(p.read_text(encoding="utf-8"))
        out: dict[tuple[str, str], panel_eval_module._ResultStr] = {}
        for key, val in raw.items():
            parts = key.split("|", 1)
            if len(parts) != 2:  # noqa: PLR2004
                console.print(
                    f"[red]error[/red] invalid key {key!r} in {path} "
                    "(expected 'item_id|criterion_id')"
                )
                raise typer.Exit(code=2)
            out[(parts[0], parts[1])] = val  # type: ignore[assignment]
        return out

    single = _load_results(single_results_json)
    panel_r = _load_results(panel_results_json)

    report = panel_eval_module.evaluate_panel_vs_single(
        gold=gold, single_results=single, panel_results=panel_r, rubric_id=rubric_id
    )

    console.print(f"\n[bold]Panel Evaluation Report — {rubric_id}[/bold]\n")
    console.print(f"  Gold pairs compared:  {report.n_gold_pairs}")
    console.print(
        f"  Single-judge  κ: {report.single_judge_kappa:.3f}  "
        f"({report.single_judge_agreement:.1%} agreement)"
    )
    console.print(
        f"  Panel         κ: {report.panel_kappa:.3f}  "
        f"({report.panel_agreement:.1%} agreement)"
    )
    delta_sign = "+" if report.delta_kappa >= 0 else ""
    console.print(f"  Δκ:                  {delta_sign}{report.delta_kappa:.3f}")
    color = "green" if report.panel_wins else "red"
    console.print(
        f"\n  [bold {color}]Recommendation: {report.recommendation.upper().replace('_', ' ')}[/bold {color}]"
    )

    if not report.panel_wins:
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# Phase 2.5 — Task store (§30)
# --------------------------------------------------------------------------- #

def _task_store() -> TaskStore:
    """Open the SQLite task store from configured settings."""
    return TaskStore(settings.tasks_db_path)


@app.command(name="task-add")
def task_add(
    title: str = typer.Argument(..., help="Task title."),
    kind: str = typer.Option("task", "--kind", "-k", help="Node kind (task/milestone/…)."),
    parent_id: str = typer.Option("", "--parent-id", help="Parent task id."),
    owner: str = typer.Option("", "--owner", help="Responsible party."),
) -> None:
    """Create a new task in the WBS tree."""
    store = _task_store()
    task = Task(
        id="",
        title=title,
        node_kind=kind,  # type: ignore[arg-type]
        parent_id=parent_id or None,
        owner=owner or None,
    )
    tid = store.create(task)
    t = store.get(tid)
    wbs = t.wbs_number if t else ""
    console.print(f"[green]created[/green] task [bold]{tid[:12]}[/bold]  wbs={wbs}  {title!r}")


@app.command(name="task-list")
def task_list(
    parent_id: str = typer.Option("", "--parent-id", help="List children of this task id."),
) -> None:
    """List tasks (roots, or children of --parent-id)."""
    store = _task_store()
    tasks = store.list_by_parent(parent_id or None)
    if not tasks:
        console.print("[yellow]no tasks[/yellow]")
        return
    table = Table(title="tasks")
    table.add_column("id")
    table.add_column("wbs")
    table.add_column("kind")
    table.add_column("status")
    table.add_column("title")
    table.add_column("owner")
    _sc = {"open": "yellow", "closed": "green", "blocked": "red"}
    for t in tasks:
        color = _sc.get(t.status, "white")
        table.add_row(
            t.id[:12],
            t.wbs_number,
            t.node_kind,
            f"[{color}]{t.status}[/{color}]",
            t.title,
            t.owner or "-",
        )
    console.print(table)


@app.command(name="task-show")
def task_show(task_id: str = typer.Argument(..., help="Task id or prefix.")) -> None:
    """Show a task and its update history."""
    store = _task_store()
    task = store.get(task_id)
    if task is None:
        console.print(f"[red]not found[/red] {task_id!r}")
        raise typer.Exit(code=2)
    console.print(f"[bold]id[/bold]       {task.id}")
    console.print(f"[bold]title[/bold]    {task.title}")
    console.print(f"[bold]kind[/bold]     {task.node_kind}")
    console.print(f"[bold]status[/bold]   {task.status}")
    console.print(f"[bold]wbs[/bold]      {task.wbs_number}")
    console.print(f"[bold]owner[/bold]    {task.owner or '-'}")
    if task.updates:
        table = Table(title="update history")
        table.add_column("when")
        table.add_column("field")
        table.add_column("old")
        table.add_column("new")
        table.add_column("by")
        for u in task.updates:
            table.add_row(
                u.timestamp.isoformat()[:19],
                u.field,
                str(u.old_value),
                str(u.new_value),
                u.changed_by,
            )
        console.print(table)


@app.command(name="task-close")
def task_close(
    task_id: str = typer.Argument(..., help="Task id to close."),
) -> None:
    """Set a task's status to closed."""
    store = _task_store()
    try:
        task = store.close_task(task_id, changed_by="cli")
    except KeyError:
        console.print(f"[red]not found[/red] {task_id!r}")
        raise typer.Exit(code=2)
    console.print(f"[green]closed[/green] {task.id[:12]}  {task.title!r}")


# --------------------------------------------------------------------------- #
# Phase 2.6 — Pendenzen (§31)
# --------------------------------------------------------------------------- #

@app.command(name="pendenz-add")
def pendenz_add(
    title: str = typer.Argument(..., help="Pendenz title."),
    source: str = typer.Option("manual", "--source", "-s", help="Source: manual|review|decision|meeting|facilitator_import."),
    source_ref: str = typer.Option("", "--source-ref", help="Id of the originating job/meeting."),
    owner: str = typer.Option("", "--owner", help="Responsible party."),
    priority: str = typer.Option("medium", "--priority", "-p", help="low|medium|high|blocker."),
) -> None:
    """Create a new pendenz (action item)."""
    store = _task_store()
    try:
        src = PendenzSource(source)
    except ValueError:
        console.print(f"[red]error[/red] unknown source {source!r}")
        raise typer.Exit(code=2)
    p = Pendenz(
        id="",
        title=title,
        source=src,
        source_ref=source_ref or None,
        owner=owner or None,
        priority=priority,  # type: ignore[arg-type]
    )
    pid = store.create(p)
    console.print(f"[green]created[/green] pendenz [bold]{pid[:12]}[/bold]  [{source}]  {title!r}")


@app.command(name="pendenz-list")
def pendenz_list(
    source: str = typer.Option("", "--source", "-s", help="Filter by source."),
) -> None:
    """List pendenzen, optionally filtered by source."""
    store = _task_store()
    all_tasks = store.list_by_parent(None)
    pendenzen = [t for t in all_tasks if t.node_kind == "pendenz"]
    if source:
        pendenzen = [
            t for t in pendenzen
            if Pendenz.model_validate(t.model_dump()).source.value == source
        ]
    if not pendenzen:
        console.print("[yellow]no pendenzen[/yellow]")
        return
    table = Table(title="pendenzen")
    table.add_column("id")
    table.add_column("source")
    table.add_column("priority")
    table.add_column("status")
    table.add_column("title")
    table.add_column("owner")
    _pc = {"blocker": "red", "high": "yellow", "medium": "white", "low": "dim"}
    _sc = {"open": "yellow", "closed": "green", "blocked": "red"}
    for t in pendenzen:
        p = Pendenz.model_validate(t.model_dump())
        pc = _pc.get(p.priority, "white")
        sc = _sc.get(t.status, "white")
        table.add_row(
            t.id[:12],
            p.source.value,
            f"[{pc}]{p.priority}[/{pc}]",
            f"[{sc}]{t.status}[/{sc}]",
            t.title,
            t.owner or "-",
        )
    console.print(table)


# --------------------------------------------------------------------------- #
# Phase 2.6 — Meetings (§31)
# --------------------------------------------------------------------------- #

def _meeting_store() -> MeetingStore:
    """Open the SQLite meeting store (shares data dir with task store)."""
    db_path = str(Path(settings.tasks_db_path).parent / "meetings.db")
    return MeetingStore(db_path)


@app.command(name="meeting-log")
def meeting_log(
    title: str = typer.Argument(..., help="Meeting title."),
    attendees: str = typer.Option(..., "--attendees", "-a", help="Comma-separated attendees."),
    notes: str = typer.Option("", "--notes", "-n", help="Raw notes text (kept local only)."),
    date_str: str = typer.Option("", "--date", "-d", help="Date YYYY-MM-DD (default: today)."),
) -> None:
    """Log a meeting note (raw notes stay local, never exported)."""
    from datetime import date as _date
    if date_str:
        try:
            meeting_date = _date.fromisoformat(date_str)
        except ValueError:
            console.print(f"[red]error[/red] invalid date {date_str!r}")
            raise typer.Exit(code=2)
    else:
        meeting_date = _date.today()

    store = _meeting_store()
    note = MeetingNote(
        title=title,
        date=meeting_date,
        attendees=[a.strip() for a in attendees.split(",") if a.strip()],
        raw_notes=notes,
    )
    mid = store.create(note)
    console.print(f"[green]logged[/green] meeting [bold]{mid[:12]}[/bold]  {title!r}  ({meeting_date})")
    console.print("[dim]raw notes stored locally only — use 'hermes meeting-extract' to extract actions[/dim]")


@app.command(name="meeting-extract")
def meeting_extract(
    meeting_id: str = typer.Argument(..., help="Meeting id."),
) -> None:
    """Extract action items from a stored meeting's raw notes."""
    store = _meeting_store()
    try:
        actions = store.extract_actions(meeting_id, client=_online_client())
    except KeyError:
        console.print(f"[red]not found[/red] meeting {meeting_id!r}")
        raise typer.Exit(code=2)
    if not actions:
        console.print("[yellow]no actions extracted[/yellow]")
        return
    table = Table(title=f"Actions from {meeting_id[:12]}")
    table.add_column("#", justify="right")
    table.add_column("action")
    for i, action in enumerate(actions, 1):
        action_str: str = action
        table.add_row(str(i), action_str)
    console.print(table)


# ---------------------------------------------------------------------------
# Phase 3.6 — Static HTML Dashboard (§31K)
# ---------------------------------------------------------------------------

def _resolve_dashboard_output(project_id: str | None, output: str) -> Path:
    """Resolve output path for the dashboard HTML file."""
    from hermes_assistant.hermes.scribe import ScribeError, safe_project_dir
    if output:
        dest = Path(output)
        if dest.suffix.lower() != ".html":
            console.print(f"[red]error[/red] --output must end in .html, got {output!r}")
            raise typer.Exit(code=2)
        if not dest.parent.exists():
            console.print(f"[red]error[/red] parent directory does not exist: {dest.parent}")
            raise typer.Exit(code=2)
        return dest
    if project_id:
        try:
            proj_dir = safe_project_dir(settings.projects_path, project_id)
        except ScribeError as exc:
            console.print(f"[red]error[/red] {exc}")
            raise typer.Exit(code=2) from exc
        proj_dir.mkdir(parents=True, exist_ok=True)
        return proj_dir / "dashboard.html"
    return Path(settings.projects_path).parent / "dashboard.html"


@app.command()
def dashboard(
    project: str = typer.Option("", "--project", "-p", help="Project id to scope the dashboard."),
    html: bool = typer.Option(False, "--html", help="Render a self-contained HTML file (§31K)."),
    output: str = typer.Option("", "--output", "-o", help="Override output path (must end in .html)."),
    open_browser: bool = typer.Option(False, "--open", help="Open the file in the default browser after writing."),
) -> None:
    """Render project dashboard (Grob-Zeitstrahl / Detail-Board / Pendenzen, spec §31K).

    Without --html, prints a brief status message. Use --html to generate a
    self-contained dashboard.html file with timeline, Kanban, and action items.
    """
    if not html:
        console.print("[yellow]P1 Rich CLI dashboard not yet implemented.[/yellow]")
        console.print("Use [cyan]--html[/cyan] to generate a static HTML dashboard.")
        return

    from hermes_assistant.dashboard_html import (
        ConfidentialityError,
        load_dashboard_data,
        render_html,
    )

    pid = project or None
    try:
        data = load_dashboard_data(pid)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Error loading dashboard data[/red]: {exc}")
        raise typer.Exit(code=2) from exc

    try:
        page = render_html(data)
    except ConfidentialityError as exc:
        console.print("[red]Confidentiality violation — dashboard not written:[/red]")
        for v in exc.violations:
            console.print(f"  - {v}")
        raise typer.Exit(code=2)

    dest = _resolve_dashboard_output(pid, output)
    try:
        dest.write_text(page, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Error writing {dest}[/red]: {exc}")
        raise typer.Exit(code=2) from exc

    console.print(f"[green]ok[/green] dashboard -> {dest}")
    console.print(
        f"  {len(page) // 1024} KB · "
        f"{len(data.timeline)} timeline items · "
        f"{len(data.pendenzen)} pendenzen"
    )
    if open_browser:
        import webbrowser
        webbrowser.open(dest.resolve().as_uri())


# ---------------------------------------------------------------------------
# P3: Interactive TUI Dashboard (§31K TUI)
# ---------------------------------------------------------------------------

@app.command()
def tui() -> None:
    """Launch interactive TUI dashboard (read-only, requires textual extra).

    Install the extra first: pip install "hermes-assistant[tui]"
    """
    import importlib.util

    if importlib.util.find_spec("textual") is None:
        console.print('[red]error[/red] TUI requires textual: pip install "hermes-assistant[tui]"')
        raise typer.Exit(code=2)

    from hermes_assistant.tui.app import run

    run()


if __name__ == "__main__":
    app()
