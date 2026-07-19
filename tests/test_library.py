"""Tests for Phase P2 library loader — models, parsing, critic/planner wiring.

All tests are fully offline: no Ollama calls.
"""

from __future__ import annotations

from pathlib import Path

from hermes_assistant.library.loader import (
    _parse_exemplar,
    _parse_failure_mode,
    load_library,
)
from hermes_assistant.library.model import Exemplar, FailureMode, LibraryIndex

_DATA_DIR = (
    Path(__file__).parent.parent
    / "src"
    / "hermes_assistant"
    / "library"
    / "data"
)


# --------------------------------------------------------------------------- #
# Model unit tests
# --------------------------------------------------------------------------- #
def test_failure_mode_defaults() -> None:
    fm = FailureMode(id="fm-x", title="X", description="Desc")
    assert fm.area == ""
    assert fm.severity == ""
    assert fm.mitigations == []


def test_exemplar_defaults() -> None:
    ex = Exemplar(id="ex-x", title="X")
    assert ex.scenario == ""
    assert ex.expected == ""
    assert ex.actual == ""
    assert ex.lesson == ""


def test_library_index_empty() -> None:
    idx = LibraryIndex()
    assert idx.failure_modes == {}
    assert idx.exemplars == {}


def test_library_index_stores_by_id() -> None:
    fm = FailureMode(id="fm-a", title="A", description="D")
    idx = LibraryIndex(failure_modes={"fm-a": fm})
    assert idx.failure_modes["fm-a"].title == "A"


# --------------------------------------------------------------------------- #
# Parser unit tests
# --------------------------------------------------------------------------- #
def test_parse_failure_mode_maps_dimension_to_area() -> None:
    raw = {
        "id": "fm-scope-creep",
        "title": "Scope creep",
        "description": "Grows without control.",
        "dimension": "completeness",
        "typical_mitigation": "Freeze scope at gate.",
    }
    fm = _parse_failure_mode(raw)
    assert fm.id == "fm-scope-creep"
    assert fm.area == "completeness"
    assert fm.mitigations == ["Freeze scope at gate."]
    assert fm.description == "Grows without control."


def test_parse_failure_mode_explicit_area_field() -> None:
    raw = {
        "id": "fm-y",
        "title": "Y",
        "description": "D",
        "area": "risk_coverage",
    }
    fm = _parse_failure_mode(raw)
    assert fm.area == "risk_coverage"


def test_parse_failure_mode_empty_mitigation_list() -> None:
    raw = {"id": "fm-z", "title": "Z", "description": "D"}
    fm = _parse_failure_mode(raw)
    assert fm.mitigations == []


def test_parse_exemplar_good_quality() -> None:
    raw = {
        "id": "ex-good",
        "title": "Good risk row",
        "project_type": "isds-analyse",
        "quality": "good",
        "content": "A well-formed row.",
        "note": "Names owner.",
    }
    ex = _parse_exemplar(raw)
    assert ex.scenario == "isds-analyse"
    assert ex.expected == "A well-formed row."
    assert ex.actual == ""
    assert ex.lesson == "Names owner."


def test_parse_exemplar_bad_quality() -> None:
    raw = {
        "id": "ex-bad",
        "title": "Placeholder row",
        "project_type": "isds-analyse",
        "quality": "bad",
        "content": "TBD.",
        "note": "Owner missing.",
    }
    ex = _parse_exemplar(raw)
    assert ex.actual == "TBD."
    assert ex.expected == ""
    assert ex.lesson == "Owner missing."


def test_parse_exemplar_unknown_quality_no_content() -> None:
    raw = {"id": "ex-u", "title": "Unknown", "quality": "other", "content": "X"}
    ex = _parse_exemplar(raw)
    assert ex.expected == ""
    assert ex.actual == ""


# --------------------------------------------------------------------------- #
# Integration: load from real YAML files
# --------------------------------------------------------------------------- #
def test_load_library_loads_failure_modes() -> None:
    idx = load_library(str(_DATA_DIR))
    assert "fm-scope-creep" in idx.failure_modes
    assert "fm-missing-owner" in idx.failure_modes
    assert "fm-unmeasurable-metric" in idx.failure_modes
    assert "fm-budget-inconsistency" in idx.failure_modes


def test_load_library_failure_mode_fields() -> None:
    idx = load_library(str(_DATA_DIR))
    fm = idx.failure_modes["fm-scope-creep"]
    assert fm.area == "completeness"
    assert len(fm.mitigations) == 1
    assert "Freeze" in fm.mitigations[0]


def test_load_library_loads_exemplars() -> None:
    idx = load_library(str(_DATA_DIR))
    assert "ex-risk-row-good" in idx.exemplars
    assert "ex-risk-row-bad" in idx.exemplars
    assert "ex-objective-good" in idx.exemplars
    assert "ex-objective-bad" in idx.exemplars


def test_load_library_exemplar_good_has_expected() -> None:
    idx = load_library(str(_DATA_DIR))
    good = idx.exemplars["ex-risk-row-good"]
    assert good.expected != ""
    assert good.actual == ""


def test_load_library_exemplar_bad_has_actual() -> None:
    idx = load_library(str(_DATA_DIR))
    bad = idx.exemplars["ex-risk-row-bad"]
    assert bad.actual != ""
    assert bad.expected == ""


def test_load_library_exemplar_lesson() -> None:
    idx = load_library(str(_DATA_DIR))
    good = idx.exemplars["ex-risk-row-good"]
    assert "owner" in good.lesson.lower()


def test_load_library_empty_dir(tmp_path: Path) -> None:
    idx = load_library(str(tmp_path))
    assert idx.failure_modes == {}
    assert idx.exemplars == {}


def test_load_library_missing_dir(tmp_path: Path) -> None:
    idx = load_library(str(tmp_path / "nonexistent"))
    assert isinstance(idx, LibraryIndex)
    assert idx.failure_modes == {}


def test_load_library_partial_dir(tmp_path: Path) -> None:
    """Only failure_modes/ subdir present — exemplars defaults to empty."""
    fm_dir = tmp_path / "failure_modes"
    fm_dir.mkdir()
    (fm_dir / "test.yaml").write_text(
        "failure_modes:\n"
        "  - id: fm-t\n"
        "    title: T\n"
        "    description: D\n",
        encoding="utf-8",
    )
    idx = load_library(str(tmp_path))
    assert "fm-t" in idx.failure_modes
    assert idx.exemplars == {}


def test_load_library_returns_library_index_type() -> None:
    idx = load_library(str(_DATA_DIR))
    assert isinstance(idx, LibraryIndex)


# --------------------------------------------------------------------------- #
# Critic wiring
# --------------------------------------------------------------------------- #
def test_critic_messages_include_failure_mode_title() -> None:
    from hermes_assistant.agents.critic import _criterion_messages
    from hermes_assistant.hermes.model import Severity
    from hermes_assistant.rubrics.model import Criterion, Dimension, Rubric

    rubric = Rubric(
        rubric_id="test",
        version="1",
        deliverable_type="plan",
        criteria=[
            Criterion(
                id="c1",
                dimension=Dimension.completeness,
                text="Has quality gate.",
                severity_if_failed=Severity.blocker,
            )
        ],
    )
    fm = FailureMode(
        id="fm-scope-creep",
        title="Uncontrolled scope creep",
        description="Scope grows without control.",
        area="completeness",
        mitigations=["Freeze scope at gate."],
    )
    msgs = _criterion_messages("doc text", rubric.criteria[0], rubric, failure_modes=[fm])
    system_text = msgs[0]["content"]
    assert "Uncontrolled scope creep" in system_text


def test_critic_messages_include_failure_mode_mitigation() -> None:
    from hermes_assistant.agents.critic import _criterion_messages
    from hermes_assistant.hermes.model import Severity
    from hermes_assistant.rubrics.model import Criterion, Dimension, Rubric

    rubric = Rubric(
        rubric_id="r",
        version="1",
        deliverable_type="plan",
        criteria=[
            Criterion(
                id="c1",
                dimension=Dimension.completeness,
                text="Check.",
                severity_if_failed=Severity.minor,
            )
        ],
    )
    fm = FailureMode(
        id="fm-x",
        title="Title X",
        description="Desc.",
        mitigations=["Apply mitigation X here."],
    )
    msgs = _criterion_messages("doc", rubric.criteria[0], rubric, failure_modes=[fm])
    assert "Apply mitigation X here." in msgs[0]["content"]


def test_critic_messages_no_failure_modes_no_fm_section() -> None:
    from hermes_assistant.agents.critic import _criterion_messages
    from hermes_assistant.hermes.model import Severity
    from hermes_assistant.rubrics.model import Criterion, Dimension, Rubric

    rubric = Rubric(
        rubric_id="r",
        version="1",
        deliverable_type="plan",
        criteria=[
            Criterion(
                id="c1",
                dimension=Dimension.completeness,
                text="Check.",
                severity_if_failed=Severity.minor,
            )
        ],
    )
    msgs_none = _criterion_messages("doc", rubric.criteria[0], rubric)
    msgs_empty = _criterion_messages("doc", rubric.criteria[0], rubric, failure_modes=[])
    assert "Known failure modes" not in msgs_none[0]["content"]
    assert msgs_none[0]["content"] == msgs_empty[0]["content"]


def test_critic_messages_multiple_failure_modes() -> None:
    from hermes_assistant.agents.critic import _criterion_messages
    from hermes_assistant.hermes.model import Severity
    from hermes_assistant.rubrics.model import Criterion, Dimension, Rubric

    rubric = Rubric(
        rubric_id="r",
        version="1",
        deliverable_type="plan",
        criteria=[
            Criterion(
                id="c1",
                dimension=Dimension.risk_coverage,
                text="Check.",
                severity_if_failed=Severity.major,
            )
        ],
    )
    fms = [
        FailureMode(id="fm-1", title="Alpha", description="D1"),
        FailureMode(id="fm-2", title="Beta", description="D2"),
    ]
    msgs = _criterion_messages("doc", rubric.criteria[0], rubric, failure_modes=fms)
    content = msgs[0]["content"]
    assert "Alpha" in content
    assert "Beta" in content


# --------------------------------------------------------------------------- #
# Planner wiring
# --------------------------------------------------------------------------- #
def test_enrichment_messages_include_exemplar_lesson() -> None:
    from hermes_assistant.hermes.model import IntakeResult
    from hermes_assistant.hermes.planner import _enrichment_messages
    from hermes_assistant.hermes.project_types import load_project_type

    intake = IntakeResult(
        project_id="p1",
        project_type="isds-analyse",
        objectives=["Secure the system"],
    )
    pt = load_project_type("isds-analyse")
    ex = Exemplar(
        id="ex-risk-row-good",
        title="Good risk row",
        scenario="isds-analyse",
        lesson="Names a single accountable owner.",
    )
    msgs = _enrichment_messages(intake, pt, exemplars=[ex])
    system_text = msgs[0]["content"]
    assert "Names a single accountable owner." in system_text


def test_enrichment_messages_include_exemplar_title() -> None:
    from hermes_assistant.hermes.model import IntakeResult
    from hermes_assistant.hermes.planner import _enrichment_messages
    from hermes_assistant.hermes.project_types import load_project_type

    intake = IntakeResult(
        project_id="p1",
        project_type="isds-analyse",
        objectives=["Check security"],
    )
    pt = load_project_type("isds-analyse")
    ex = Exemplar(id="ex-x", title="MyExemplar", lesson="Key lesson here.")
    msgs = _enrichment_messages(intake, pt, exemplars=[ex])
    assert "MyExemplar" in msgs[0]["content"]


def test_enrichment_messages_no_exemplars_no_lesson_section() -> None:
    from hermes_assistant.hermes.model import IntakeResult
    from hermes_assistant.hermes.planner import _enrichment_messages
    from hermes_assistant.hermes.project_types import load_project_type

    intake = IntakeResult(
        project_id="p1",
        project_type="isds-analyse",
        objectives=["Baseline check"],
    )
    pt = load_project_type("isds-analyse")
    msgs_none = _enrichment_messages(intake, pt)
    msgs_empty = _enrichment_messages(intake, pt, exemplars=[])
    assert "Lessons from past-project exemplars" not in msgs_none[0]["content"]
    assert msgs_none[0]["content"] == msgs_empty[0]["content"]


def test_enrichment_messages_good_content_snippet() -> None:
    from hermes_assistant.hermes.model import IntakeResult
    from hermes_assistant.hermes.planner import _enrichment_messages
    from hermes_assistant.hermes.project_types import load_project_type

    intake = IntakeResult(
        project_id="p1",
        project_type="isds-analyse",
        objectives=["Review"],
    )
    pt = load_project_type("isds-analyse")
    ex = Exemplar(
        id="ex-good",
        title="T",
        expected="The expected good content snippet.",
        lesson="L",
    )
    msgs = _enrichment_messages(intake, pt, exemplars=[ex])
    assert "The expected good content snippet." in msgs[0]["content"]
