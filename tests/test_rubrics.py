"""Rubric model & loader tests — YAML load, version resolution, validation."""

from pathlib import Path

import pytest

from hermes_assistant.hermes.model import Severity
from hermes_assistant.rubrics.loader import (
    RubricError,
    list_rubrics,
    load_rubric,
)
from hermes_assistant.rubrics.model import Dimension

SEED_CRITERIA = 12
SEED_ANTIPATTERNS = 3


def test_load_seed_rubric() -> None:
    """The shipped project-plan rubric loads with the expected shape."""
    rubric = load_rubric("project-plan")
    assert rubric.rubric_id == "project-plan"
    assert rubric.version == "1"
    assert rubric.deliverable_type == "ProjectPlan"
    assert len(rubric.criteria) == SEED_CRITERIA
    assert len(rubric.anti_patterns) == SEED_ANTIPATTERNS


def test_seed_rubric_covers_five_dimensions() -> None:
    """The seed rubric spans all five quality dimensions."""
    rubric = load_rubric("project-plan")
    assert set(rubric.dimensions()) == set(Dimension)


def test_seed_rubric_has_a_blocker_criterion() -> None:
    """[AC1] At least one criterion is a blocker (the quality-gate check)."""
    rubric = load_rubric("project-plan")
    blockers = [c for c in rubric.criteria if c.severity_if_failed is Severity.blocker]
    assert any(c.id == "every_phase_quality_gate" for c in blockers)


def test_list_rubrics_includes_seed() -> None:
    """list_rubrics returns (id, version) pairs including the seed."""
    assert ("project-plan", "1") in list_rubrics()


def _write_rubric(directory: Path, name: str, rubric_id: str, version: str) -> None:
    (directory / name).write_text(
        f"""
rubric_id: {rubric_id}
version: "{version}"
deliverable_type: Thing
criteria:
  - id: c1
    dimension: completeness
    text: A criterion.
    severity_if_failed: major
""",
        encoding="utf-8",
    )


def test_version_resolution_picks_highest(tmp_path: Path) -> None:
    """With v1 and v2 present, load_rubric(id) resolves to v2."""
    _write_rubric(tmp_path, "demo.v1.yaml", "demo", "1")
    _write_rubric(tmp_path, "demo.v2.yaml", "demo", "2")
    rubric = load_rubric("demo", base_dir=tmp_path)
    assert rubric.version == "2"


def test_pin_specific_version(tmp_path: Path) -> None:
    """A pinned version (v1 / 'v1' / 1) is honoured over the highest."""
    _write_rubric(tmp_path, "demo.v1.yaml", "demo", "1")
    _write_rubric(tmp_path, "demo.v2.yaml", "demo", "2")
    assert load_rubric("demo", "v1", base_dir=tmp_path).version == "1"
    assert load_rubric("demo", 1, base_dir=tmp_path).version == "1"


def test_unknown_rubric_raises(tmp_path: Path) -> None:
    """An unknown rubric id raises RubricError."""
    with pytest.raises(RubricError, match="Unknown rubric"):
        load_rubric("ghost", base_dir=tmp_path)


def test_unknown_version_raises(tmp_path: Path) -> None:
    """Pinning a non-existent version raises RubricError."""
    _write_rubric(tmp_path, "demo.v1.yaml", "demo", "1")
    with pytest.raises(RubricError, match="no version"):
        load_rubric("demo", 9, base_dir=tmp_path)


def test_duplicate_criterion_id_rejected(tmp_path: Path) -> None:
    """A rubric with duplicate criterion ids fails to load."""
    (tmp_path / "dup.v1.yaml").write_text(
        """
rubric_id: dup
version: "1"
deliverable_type: Thing
criteria:
  - id: c1
    dimension: completeness
    text: First.
    severity_if_failed: major
  - id: c1
    dimension: clarity
    text: Duplicate id.
    severity_if_failed: minor
""",
        encoding="utf-8",
    )
    with pytest.raises(RubricError, match="Duplicate criterion id"):
        load_rubric("dup", base_dir=tmp_path)


def test_empty_criteria_rejected(tmp_path: Path) -> None:
    """A rubric declaring no criteria is rejected."""
    (tmp_path / "empty.v1.yaml").write_text(
        'rubric_id: empty\nversion: "1"\ndeliverable_type: Thing\ncriteria: []\n',
        encoding="utf-8",
    )
    with pytest.raises(RubricError, match="no criteria"):
        load_rubric("empty", base_dir=tmp_path)
