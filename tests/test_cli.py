"""CLI smoke tests (offline)."""

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from hermes_assistant.cli import app
from hermes_assistant.config import settings
from hermes_assistant.llm.client import OllamaClient

from .conftest import FIXTURES, FakeEmbedder

runner = CliRunner()

ISDS_DESCRIPTION = FIXTURES / "isds_sample_description.txt"


def test_plan_from_description_emits_valid_projectplan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[AC1] `hermes plan` on the sample description emits a plan with all
    mandatory outcomes, quality gates and minimum roles — fully offline."""
    monkeypatch.setattr(settings, "projects_path", str(tmp_path / "proj"))
    with patch("hermes_assistant.cli._online_client", return_value=None):
        result = runner.invoke(
            app, ["plan", str(ISDS_DESCRIPTION), "--project", "fin-isds"]
        )
    assert result.exit_code == 0, result.stdout

    from hermes_assistant.hermes.model import ProjectPlan

    plan_json = tmp_path / "proj" / "fin-isds" / "plan.json"
    assert plan_json.is_file()
    plan = ProjectPlan.model_validate_json(plan_json.read_text(encoding="utf-8"))
    ids = {oc.id for ph in plan.phases for oc in ph.outcomes}
    assert {"informatikschutzobjekt", "schutzbedarf", "risikoanalyse", "massnahmen"} <= ids
    assert {"Auftraggeber", "Projektleiter", "ISBO"} <= set(plan.roles)
    assert all(any(m.is_quality_gate for m in ph.milestones) for ph in plan.phases)
    # All four artifacts exist.
    for name in ("intake.json", "plan.json", "plan.md", "decisions.md"):
        assert (tmp_path / "proj" / "fin-isds" / name).is_file()


def test_check_plan_flags_injected_defects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[AC2] `hermes check-plan` flags a removed outcome AND role, exit code 1."""
    monkeypatch.setattr(settings, "projects_path", str(tmp_path / "proj"))
    with patch("hermes_assistant.cli._online_client", return_value=None):
        built = runner.invoke(
            app, ["plan", str(ISDS_DESCRIPTION), "--project", "fin-isds"]
        )
    assert built.exit_code == 0, built.stdout

    proj = tmp_path / "proj" / "fin-isds"
    intake_json = proj / "intake.json"
    plan_json = proj / "plan.json"

    # Clean plan passes.
    ok = runner.invoke(app, ["check-plan", str(plan_json), "--intake", str(intake_json)])
    assert ok.exit_code == 0
    assert "no flags" in ok.stdout

    # Inject the two defects into plan.json and re-check.
    from hermes_assistant.hermes.model import ProjectPlan

    plan = ProjectPlan.model_validate_json(plan_json.read_text(encoding="utf-8"))
    for phase in plan.phases:
        phase.outcomes = [oc for oc in phase.outcomes if oc.id != "schutzbedarf"]
    plan.roles = [r for r in plan.roles if r != "ISBO"]
    plan_json.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    flagged = runner.invoke(
        app, ["check-plan", str(plan_json), "--intake", str(intake_json)]
    )
    assert flagged.exit_code == 1
    assert "missing_outcome" in flagged.stdout
    assert "unassigned_role" in flagged.stdout


def test_intake_writes_intake_json_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`hermes intake` writes intake.json even with Ollama offline (no router)."""
    monkeypatch.setattr(settings, "projects_path", str(tmp_path / "proj"))
    with patch("hermes_assistant.cli._online_client", return_value=None):
        result = runner.invoke(
            app, ["intake", str(ISDS_DESCRIPTION), "--project", "fin-isds"]
        )
    assert result.exit_code == 0, result.stdout
    intake_json = tmp_path / "proj" / "fin-isds" / "intake.json"
    assert intake_json.is_file()
    assert "isds-analyse" in intake_json.read_text(encoding="utf-8")


def test_intake_malformed_project_id_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[B2] `hermes intake` with a traversal project id exits 1 before writing."""
    monkeypatch.setattr(settings, "projects_path", str(tmp_path / "proj"))
    with patch("hermes_assistant.cli._online_client", return_value=None):
        result = runner.invoke(
            app, ["intake", "some description", "--project", "../evil"]
        )
    assert result.exit_code == 1
    assert not (tmp_path / "proj" / ".." / "evil").exists()


def test_init_creates_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`hermes init` creates the configured local data directories."""
    monkeypatch.setattr(settings, "vectorstore_path", str(tmp_path / "vs"))
    monkeypatch.setattr(settings, "projects_path", str(tmp_path / "proj"))
    monkeypatch.setattr(settings, "traces_path", str(tmp_path / "traces/llm.jsonl"))

    result = runner.invoke(app, ["init"])

    assert result.exit_code == 0
    assert (tmp_path / "vs").is_dir()
    assert (tmp_path / "proj").is_dir()
    assert (tmp_path / "traces").is_dir()


def test_models_lists_roster_offline() -> None:
    """`hermes models` lists the roster and tolerates an offline Ollama."""
    offline = {"available": False, "host": "x", "models": [], "error": "down"}
    with patch.object(OllamaClient, "health", return_value=offline):
        result = runner.invoke(app, ["models"])

    assert result.exit_code == 0
    assert "qwen3:4b" in result.stdout
    assert "offline" in result.stdout.lower()


def test_models_marks_pulled_models() -> None:
    """Installed models are marked pulled when Ollama is reachable."""
    available = {
        "available": True,
        "host": "x",
        "models": ["qwen3:4b"],
        "error": None,
    }
    with patch.object(OllamaClient, "health", return_value=available):
        result = runner.invoke(app, ["models"])

    assert result.exit_code == 0
    assert "pulled" in result.stdout


def test_ingest_and_show_end_to_end(
    tmp_path: Path, sample_md: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`hermes ingest` then `hermes show` work end-to-end (fake embedder)."""
    monkeypatch.setattr(settings, "vectorstore_path", str(tmp_path / "vs"))
    with patch("hermes_assistant.cli._client", return_value=FakeEmbedder()):
        ingest_result = runner.invoke(app, ["ingest", str(sample_md)])
        assert ingest_result.exit_code == 0, ingest_result.stdout
        assert "added" in ingest_result.stdout

        # `show` by source path lists the file's chunks.
        show_source = runner.invoke(app, ["show", str(sample_md)])
        assert show_source.exit_code == 0
        assert "Chunks from" in show_source.stdout


def test_ingest_reports_failure_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A parse failure yields a FAILED row and a non-zero exit code."""
    monkeypatch.setattr(settings, "vectorstore_path", str(tmp_path / "vs"))
    bad = tmp_path / "bad.docx"
    bad.write_text("not a docx", encoding="utf-8")
    with patch("hermes_assistant.cli._client", return_value=FakeEmbedder()):
        result = runner.invoke(app, ["ingest", str(bad)])
    assert result.exit_code == 1
    assert "failed" in result.stdout.lower()


def test_show_not_found_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`hermes show` on an unknown identifier exits non-zero."""
    monkeypatch.setattr(settings, "vectorstore_path", str(tmp_path / "vs"))
    result = runner.invoke(app, ["show", "does-not-exist"])
    assert result.exit_code == 1
    assert "not found" in result.stdout.lower()
