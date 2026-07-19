"""Intake router + question-engine tests (offline, mocked router)."""

from hermes_assistant.hermes.intake import run_intake
from hermes_assistant.hermes.model import IntakeResult


class FakeRouter:
    """Duck-typed stand-in exposing only ``structured`` (returns a preset)."""

    def __init__(self, extraction: IntakeResult) -> None:
        self.extraction = extraction
        self.calls = 0

    def structured(self, model: str, messages: list, schema: type) -> IntakeResult:
        self.calls += 1
        return self.extraction


def test_classification_valid_type_is_kept() -> None:
    """A router classification within the taxonomy is preserved."""
    ex = IntakeResult(project_id="x", project_type="isds-analyse")
    result = run_intake("desc", "p1", client=FakeRouter(ex), answers={})
    assert result.project_type == "isds-analyse"


def test_classification_out_of_taxonomy_is_coerced() -> None:
    """An off-taxonomy classification is coerced to a valid type (enum-constrained)."""
    ex = IntakeResult(project_id="x", project_type="totally-made-up")
    result = run_intake("desc", "p1", client=FakeRouter(ex), answers={})
    assert result.project_type == "isds-analyse"


def test_extracted_field_is_not_re_asked() -> None:
    """A field the router pre-answered is never overwritten by the question engine."""
    ex = IntakeResult(project_id="x", project_type="isds-analyse",
                      objectives=["Assess the ISDS"])
    # Even though an answer is supplied for the same question, it must be ignored.
    result = run_intake("desc", "p1", client=FakeRouter(ex),
                        answers={"q_objectives": ["SHOULD NOT WIN"]})
    assert result.objectives == ["Assess the ISDS"]


def test_missing_field_is_filled_from_answers() -> None:
    """A field the router left empty is filled from the non-interactive answers."""
    ex = IntakeResult(project_id="x", project_type="isds-analyse")
    result = run_intake("desc", "p1", client=FakeRouter(ex),
                        answers={"q_scope": ["bank accounts"]})
    assert result.scope == ["bank accounts"]


def test_sizing_flag_captured_from_answer() -> None:
    """A sizing question answer sets the corresponding boolean flag."""
    ex = IntakeResult(project_id="x", project_type="isds-analyse")
    result = run_intake("desc", "p1", client=FakeRouter(ex),
                        answers={"q_protection_need": True})
    assert result.sizing_flags.get("high_protection_need") is True


def test_blindspot_answer_recorded_as_known_unknown() -> None:
    """Junior blind-spot answers surface as known_unknowns."""
    ex = IntakeResult(project_id="x", project_type="isds-analyse")
    result = run_intake("desc", "p1", client=FakeRouter(ex),
                        answers={"q_restrisiko_owner": "Auftraggeber"})
    assert "Auftraggeber" in result.known_unknowns


def test_no_client_no_description_uses_answers_only() -> None:
    """Without a router, the type falls back and answers alone populate fields."""
    result = run_intake(None, "p1", client=None, answers={"q_scope": ["s"]})
    assert result.project_type == "isds-analyse"
    assert result.scope == ["s"]
