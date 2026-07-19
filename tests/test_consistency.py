"""Consistency / MECE checker unit tests (fully deterministic, no LLM).

Tests cover all three violation categories (MECE, numeric, cross-section),
the ``ConsistencyError`` shape, and the CLI ``consistency-check`` command.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from hermes_assistant.agents.consistency import (
    ConsistencyError,
    ConsistencyReport,
    check_consistency,
)
from hermes_assistant.cli import app
from hermes_assistant.config import settings
from hermes_assistant.hermes.model import Milestone, Outcome, Phase, ProjectPlan

runner = CliRunner()


# --------------------------------------------------------------------------- #
# Fixture helpers
# --------------------------------------------------------------------------- #
def _outcome(
    id: str,
    name: str = "Generic Outcome",
    *,
    phase: str = "",
    effort_days: float | None = None,
    depends_on: list[str] | None = None,
) -> Outcome:
    return Outcome(
        id=id,
        name=name,
        kind="document",
        mandatory=True,
        module="m",
        phase=phase,
        effort_days=effort_days,
        depends_on=depends_on or [],
    )


def _milestone(
    id: str,
    name: str = "Quality Gate",
    *,
    effort_days: float | None = None,
    depends_on: list[str] | None = None,
) -> Milestone:
    return Milestone(
        id=id,
        name=name,
        is_quality_gate=True,
        effort_days=effort_days,
        depends_on=depends_on or [],
    )


def _phase(
    id: str,
    name: str,
    *,
    milestones: list[Milestone] | None = None,
    outcomes: list[Outcome] | None = None,
) -> Phase:
    return Phase(
        id=id,
        name=name,
        milestones=milestones or [],
        outcomes=outcomes or [],
    )


def _clean_plan() -> ProjectPlan:
    return ProjectPlan(
        title="Clean Plan",
        scenario="Test scenario",
        approach="traditional",
        phases=[
            _phase(
                "p1",
                "Phase 1",
                milestones=[_milestone("ms1")],
                outcomes=[_outcome("oc1", "Charter")],
            ),
            _phase(
                "p2",
                "Phase 2",
                milestones=[_milestone("ms2")],
                outcomes=[_outcome("oc2", "Concept")],
            ),
        ],
        roles=["PM"],
    )


# --------------------------------------------------------------------------- #
# Clean plan — no violations
# --------------------------------------------------------------------------- #
def test_clean_plan_returns_report() -> None:
    report = check_consistency(_clean_plan())
    assert isinstance(report, ConsistencyReport)
    assert report.ok
    assert report.mece_violations == []
    assert report.numeric_contradictions == []
    assert report.cross_checks == []


def test_report_ok_property_false_when_violations_exist() -> None:
    plan = _clean_plan()
    plan.phases.append(
        _phase("p3", "Empty Phase", milestones=[_milestone("ms3")])
    )
    with pytest.raises(ConsistencyError) as exc_info:
        check_consistency(plan)
    # If we could get the report without raising we'd check ok=False.
    # Validate via the error shape instead.
    assert len(exc_info.value.violations) >= 1


def test_all_violations_combines_all_categories() -> None:
    """all_violations is the union of all three violation lists."""
    report = ConsistencyReport(
        mece_violations=["a"],
        numeric_contradictions=["b", "c"],
        cross_checks=["d"],
    )
    assert report.all_violations == ["a", "b", "c", "d"]
    assert not report.ok


# --------------------------------------------------------------------------- #
# MECE violations
# --------------------------------------------------------------------------- #
def test_duplicate_outcome_ids_raises() -> None:
    plan = _clean_plan()
    # Add a second outcome with the same id inside the same phase.
    plan.phases[0].outcomes.append(_outcome("oc1", "Duplicate Name"))
    with pytest.raises(ConsistencyError) as exc_info:
        check_consistency(plan)
    assert any("oc1" in v for v in exc_info.value.violations)


def test_duplicate_outcome_names_raises() -> None:
    plan = _clean_plan()
    # "Charter" already in p1; add same name under a different id in p2.
    plan.phases[1].outcomes.append(_outcome("oc99", "Charter"))
    with pytest.raises(ConsistencyError) as exc_info:
        check_consistency(plan)
    assert any("charter" in v.lower() for v in exc_info.value.violations)


def test_duplicate_milestone_ids_raises() -> None:
    plan = _clean_plan()
    # ms1 already in p1; reuse in p2.
    plan.phases[1].milestones.append(_milestone("ms1"))
    with pytest.raises(ConsistencyError) as exc_info:
        check_consistency(plan)
    assert any("ms1" in v for v in exc_info.value.violations)


def test_empty_phase_outcomes_raises() -> None:
    plan = _clean_plan()
    plan.phases.append(
        _phase("p3", "Empty Phase", milestones=[_milestone("ms3")])
    )
    with pytest.raises(ConsistencyError) as exc_info:
        check_consistency(plan)
    assert any("p3" in v for v in exc_info.value.violations)


# --------------------------------------------------------------------------- #
# Numeric contradictions
# --------------------------------------------------------------------------- #
def test_negative_effort_days_outcome_raises() -> None:
    plan = _clean_plan()
    plan.phases[0].outcomes[0] = _outcome("oc1", "Charter", effort_days=-1.0)
    with pytest.raises(ConsistencyError) as exc_info:
        check_consistency(plan)
    violations = exc_info.value.violations
    assert any("oc1" in v and "effort_days" in v for v in violations)


def test_zero_effort_days_milestone_raises() -> None:
    plan = _clean_plan()
    plan.phases[0].milestones[0] = _milestone("ms1", effort_days=0.0)
    with pytest.raises(ConsistencyError) as exc_info:
        check_consistency(plan)
    violations = exc_info.value.violations
    assert any("ms1" in v and "effort_days" in v for v in violations)


def test_positive_effort_days_no_violation() -> None:
    plan = _clean_plan()
    plan.phases[0].outcomes[0] = _outcome("oc1", "Charter", effort_days=2.0)
    plan.phases[0].milestones[0] = _milestone("ms1", effort_days=1.0)
    report = check_consistency(plan)
    assert report.ok


# --------------------------------------------------------------------------- #
# Cross-section checks
# --------------------------------------------------------------------------- #
def test_dangling_depends_on_outcome_raises() -> None:
    plan = _clean_plan()
    plan.phases[0].outcomes[0] = _outcome(
        "oc1", "Charter", depends_on=["ghost_id"]
    )
    with pytest.raises(ConsistencyError) as exc_info:
        check_consistency(plan)
    assert any("ghost_id" in v for v in exc_info.value.violations)


def test_dangling_depends_on_milestone_raises() -> None:
    plan = _clean_plan()
    plan.phases[0].milestones[0] = _milestone(
        "ms1", depends_on=["ghost_ms"]
    )
    with pytest.raises(ConsistencyError) as exc_info:
        check_consistency(plan)
    assert any("ghost_ms" in v for v in exc_info.value.violations)


def test_outcome_phase_mismatch_raises() -> None:
    plan = _clean_plan()
    # oc1 is in phase p1 but declares phase="p_wrong"
    plan.phases[0].outcomes[0] = _outcome("oc1", "Charter", phase="p_wrong")
    with pytest.raises(ConsistencyError) as exc_info:
        check_consistency(plan)
    assert any("p_wrong" in v for v in exc_info.value.violations)


def test_valid_depends_on_same_plan_no_violation() -> None:
    """An outcome depending on another existing id is never a violation."""
    plan = _clean_plan()
    plan.phases[1].outcomes[0] = _outcome(
        "oc2", "Concept", depends_on=["oc1"]
    )
    report = check_consistency(plan)
    assert report.ok


def test_empty_phase_field_no_mismatch_violation() -> None:
    """phase='' (the default) never triggers the mismatch check."""
    plan = _clean_plan()
    plan.phases[0].outcomes[0] = _outcome("oc1", "Charter", phase="")
    report = check_consistency(plan)
    assert report.ok


# --------------------------------------------------------------------------- #
# ConsistencyError shape
# --------------------------------------------------------------------------- #
def test_consistency_error_has_violations_list() -> None:
    plan = _clean_plan()
    plan.phases.append(
        _phase("p3", "Stray Phase", milestones=[_milestone("ms3")])
    )
    with pytest.raises(ConsistencyError) as exc_info:
        check_consistency(plan)
    err = exc_info.value
    assert isinstance(err.violations, list)
    assert len(err.violations) >= 1
    assert str(err)  # __str__ includes count + preview


def test_consistency_error_str_has_count() -> None:
    err = ConsistencyError(["v1", "v2", "v3"])
    assert "3" in str(err)


# --------------------------------------------------------------------------- #
# CLI smoke tests
# --------------------------------------------------------------------------- #
def test_consistency_check_cmd_plan_not_found_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "projects_path", str(tmp_path))
    result = runner.invoke(app, ["consistency-check", "no-such-project"])
    assert result.exit_code == 2
    assert "not found" in result.stdout.lower()


def test_consistency_check_cmd_clean_plan_exits_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "projects_path", str(tmp_path))
    proj_dir = tmp_path / "clean"
    proj_dir.mkdir()
    (proj_dir / "plan.json").write_text(
        _clean_plan().model_dump_json(indent=2), encoding="utf-8"
    )
    result = runner.invoke(app, ["consistency-check", "clean"])
    assert result.exit_code == 0, result.stdout
    assert "no consistency violations" in result.stdout.lower()


def test_consistency_check_cmd_violations_exit_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plan with a duplicate outcome id causes exit 1 and prints the violation."""
    monkeypatch.setattr(settings, "projects_path", str(tmp_path))
    proj_dir = tmp_path / "bad"
    proj_dir.mkdir()

    bad_plan = ProjectPlan(
        title="Violated Plan",
        scenario="Test",
        approach="traditional",
        phases=[
            Phase(
                id="p1",
                name="Phase 1",
                milestones=[_milestone("ms1")],
                outcomes=[
                    _outcome("oc1", "Charter"),
                    _outcome("oc1", "Charter Copy"),  # duplicate id
                ],
            )
        ],
        roles=["PM"],
    )
    (proj_dir / "plan.json").write_text(
        bad_plan.model_dump_json(indent=2), encoding="utf-8"
    )
    result = runner.invoke(app, ["consistency-check", "bad"])
    assert result.exit_code == 1
    assert "oc1" in result.stdout
