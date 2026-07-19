"""Scribe writer & path-traversal tests (pure, offline)."""

import json
from pathlib import Path

import pytest

from hermes_assistant.hermes.model import Flag, IntakeResult, Severity
from hermes_assistant.hermes.planner import build_skeleton
from hermes_assistant.hermes.project_types import load_project_type
from hermes_assistant.hermes.scribe import ScribeError, safe_project_dir, write_artifacts


def _intake(project_id: str = "proj1") -> IntakeResult:
    return IntakeResult(project_id=project_id, project_type="isds-analyse",
                        objectives=["Assess the ISDS"], known_unknowns=["Who signs off?"])


def test_write_artifacts_creates_four_files(tmp_path: Path) -> None:
    """All four artifacts are written under base/<project_id>."""
    intake = _intake()
    plan = build_skeleton(intake, load_project_type("isds-analyse"))
    paths = write_artifacts(tmp_path, intake, plan)

    assert set(paths) == {"intake", "plan", "plan_md", "decisions"}
    for path in paths.values():
        assert path.is_file()
        assert path.stat().st_size > 0

    # JSON artifacts are valid and round-trip.
    loaded = json.loads(paths["intake"].read_text(encoding="utf-8"))
    assert loaded["project_id"] == "proj1"
    assert "# " in paths["plan_md"].read_text(encoding="utf-8")
    assert "Decision log" in paths["decisions"].read_text(encoding="utf-8")


@pytest.mark.parametrize("bad_id", ["../evil", "a/b", "..", "", "/abs", "x\\y"])
def test_safe_project_dir_rejects_traversal(tmp_path: Path, bad_id: str) -> None:
    """Any id with a separator, traversal, or absolute path is rejected."""
    with pytest.raises(ScribeError):
        safe_project_dir(tmp_path, bad_id)


def test_safe_project_dir_accepts_clean_id(tmp_path: Path) -> None:
    """A well-formed id resolves to a child of the base directory."""
    target = safe_project_dir(tmp_path, "fin-isds_2026.1")
    assert target.parent == tmp_path.resolve()


def test_write_artifacts_rejects_unsafe_project_id(tmp_path: Path) -> None:
    """write_artifacts propagates the traversal guard via the intake id."""
    intake = _intake(project_id="../escape")
    plan = build_skeleton(_intake(), load_project_type("isds-analyse"))
    with pytest.raises(ScribeError):
        write_artifacts(tmp_path, intake, plan)


def test_decisions_md_appends_on_second_run(tmp_path: Path) -> None:
    """[B1] A second write_artifacts call appends to decisions.md, not overwrites."""
    intake = _intake()
    plan = build_skeleton(intake, load_project_type("isds-analyse"))
    write_artifacts(tmp_path, intake, plan)
    write_artifacts(tmp_path, intake, plan)
    content = (tmp_path / "proj1" / "decisions.md").read_text(encoding="utf-8")
    # Two runs → two "Decision log" headings.
    assert content.count("# Decision log") == 2


def test_decisions_md_records_flags(tmp_path: Path) -> None:
    """[B1] Checker flags passed to write_artifacts appear in decisions.md."""
    intake = _intake()
    plan = build_skeleton(intake, load_project_type("isds-analyse"))
    flags = [
        Flag(kind="missing_outcome", detail="schutzbedarf absent", severity=Severity.blocker),
        Flag(kind="unassigned_role", detail="ISBO missing", severity=Severity.blocker),
    ]
    write_artifacts(tmp_path, intake, plan, flags=flags)
    content = (tmp_path / "proj1" / "decisions.md").read_text(encoding="utf-8")
    assert "missing_outcome" in content
    assert "schutzbedarf absent" in content
    assert "unassigned_role" in content
