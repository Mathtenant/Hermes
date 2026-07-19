"""Schema flattening & structured-output validation tests."""

import json
from unittest.mock import MagicMock

from pydantic import BaseModel

from hermes_assistant.hermes.model import Finding, ReviewResult, Verdict
from hermes_assistant.llm.client import OllamaClient, _flatten_schema

from .conftest import make_response


class SampleModel(BaseModel):
    """Sample model for retry tests."""

    name: str
    value: int


def _valid_review() -> ReviewResult:
    return ReviewResult(
        rubric_id="isds-v1",
        rubric_version="1.0",
        deliverable_type="ISDS",
        findings=[
            Finding(
                criterion_id="c1",
                dimension="completeness",
                result="pass",
                severity=None,
                location="section 3",
                evidence_quote="verbatim",
                rationale="reasoned",
                fix_suggestion="none",
                confidence=0.9,
            )
        ],
        dimension_summary={"completeness": "ok"},
        blockers=0,
        majors=0,
        minors=0,
        verdict=Verdict.pass_,
        verdict_rationale="meets criteria",
    )


def test_flatten_removes_refs_finding() -> None:
    """Flattening a flat model is a no-op for refs but drops $defs."""
    flat = _flatten_schema(Finding.model_json_schema())
    blob = json.dumps(flat)
    assert "$ref" not in blob
    assert "$defs" not in blob


def test_flatten_removes_refs_reviewresult() -> None:
    """Nested ReviewResult has its $ref/$defs fully inlined."""
    raw = ReviewResult.model_json_schema()
    assert "$defs" in json.dumps(raw)  # precondition: nested model has defs

    flat = _flatten_schema(raw)
    blob = json.dumps(flat)
    assert "$ref" not in blob
    assert "$defs" not in blob


def test_flatten_inlines_nested_finding_fields() -> None:
    """The inlined Finding properties are reachable under findings.items."""
    flat = _flatten_schema(ReviewResult.model_json_schema())
    item = flat["properties"]["findings"]["items"]
    assert "criterion_id" in item["properties"]
    assert "evidence_quote" in item["properties"]


def test_structured_payload_uses_flattened_format(
    client: OllamaClient, mock_post: MagicMock
) -> None:
    """The format sent to Ollama is the flattened (ref-free) schema."""
    review = _valid_review()
    mock_post.return_value = make_response(
        {"message": {"content": review.model_dump_json()}}
    )

    result = client.structured(
        "m", [{"role": "user", "content": "review"}], ReviewResult
    )

    assert isinstance(result, ReviewResult)
    assert result.verdict is Verdict.pass_
    sent_format = mock_post.call_args.kwargs["json"]["format"]
    assert "$ref" not in json.dumps(sent_format)
    assert "$defs" not in json.dumps(sent_format)


def test_use_case_rejected_retried_passed(
    client: OllamaClient, mock_post: MagicMock
) -> None:
    """Use case 2: structured output rejected -> retried -> passes."""
    mock_post.side_effect = [
        make_response({"message": {"content": '{"name": "x", "value": "BAD"}'}}),
        make_response({"message": {"content": '{"name": "x", "value": 7}'}}),
    ]

    result = client.structured(
        "m", [{"role": "user", "content": "json"}], SampleModel, max_retries=1
    )

    assert result.value == 7
    assert mock_post.call_count == 2
    # Second attempt prompt must carry the validation feedback.
    second_payload = mock_post.call_args_list[1].kwargs["json"]
    assert any(
        "Validation error" in m["content"] for m in second_payload["messages"]
    )
