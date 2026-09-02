"""Tests for OllamaClient (mocked Ollama, fully offline)."""

from unittest.mock import MagicMock

import pytest
import requests
from pydantic import BaseModel

from hermes_assistant.llm.client import (
    OllamaClient,
    OllamaConnectionError,
    OllamaTimeoutError,
    OllamaValidationError,
)

from .conftest import make_response


class SampleModel(BaseModel):
    """Sample Pydantic model for structured-output tests."""

    name: str
    value: int


def test_chat(client: OllamaClient, mock_post: MagicMock) -> None:
    """Basic chat completion returns the message content."""
    mock_post.return_value = make_response({"message": {"content": "Hello, world!"}})

    result = client.chat("test-model", [{"role": "user", "content": "Hi"}])

    assert result == "Hello, world!"
    mock_post.assert_called_once()


def test_chat_think_is_top_level(client: OllamaClient, mock_post: MagicMock) -> None:
    """`think` must be a top-level field, NOT nested under options."""
    mock_post.return_value = make_response({"message": {"content": "ok"}})

    client.chat("m", [{"role": "user", "content": "x"}], think=True)

    payload = mock_post.call_args.kwargs["json"]
    assert payload["think"] is True
    assert "think" not in payload["options"]
    assert "reasoning" not in payload["options"]


def test_structured_valid_json(client: OllamaClient, mock_post: MagicMock) -> None:
    """Valid JSON is parsed into the Pydantic model."""
    mock_post.return_value = make_response(
        {"message": {"content": '{"name": "test", "value": 42}'}}
    )

    result = client.structured(
        "test-model", [{"role": "user", "content": "Generate JSON"}], SampleModel
    )

    assert isinstance(result, SampleModel)
    assert result.name == "test"
    assert result.value == 42


def test_structured_invalid_json_retry(
    client: OllamaClient, mock_post: MagicMock
) -> None:
    """Invalid JSON triggers one retry, then succeeds."""
    mock_post.side_effect = [
        make_response({"message": {"content": "{invalid json}"}}),
        make_response({"message": {"content": '{"name": "fixed", "value": 99}'}}),
    ]

    result = client.structured(
        "test-model",
        [{"role": "user", "content": "Generate JSON"}],
        SampleModel,
        max_retries=1,
    )

    assert result.name == "fixed"
    assert result.value == 99
    assert mock_post.call_count == 2


def test_structured_validation_error_retry(
    client: OllamaClient, mock_post: MagicMock
) -> None:
    """Wrong types trigger a retry, then succeed."""
    mock_post.side_effect = [
        make_response({"message": {"content": '{"name": "test", "value": "nope"}'}}),
        make_response({"message": {"content": '{"name": "test", "value": 123}'}}),
    ]

    result = client.structured(
        "test-model",
        [{"role": "user", "content": "Generate JSON"}],
        SampleModel,
        max_retries=1,
    )

    assert result.value == 123
    assert mock_post.call_count == 2


def test_structured_exhausts_retries_raises(
    client: OllamaClient, mock_post: MagicMock
) -> None:
    """After retries are exhausted, OllamaValidationError is raised."""
    mock_post.side_effect = [
        make_response({"message": {"content": "{bad}"}}),
        make_response({"message": {"content": "{still bad}"}}),
    ]

    with pytest.raises(OllamaValidationError) as exc:
        client.structured(
            "m", [{"role": "user", "content": "x"}], SampleModel, max_retries=1
        )

    assert exc.value.last_raw == "{still bad}"
    assert mock_post.call_count == 2


def test_embed(client: OllamaClient, mock_post: MagicMock) -> None:
    """Embeddings return the first vector."""
    mock_post.return_value = make_response({"embeddings": [[0.1, 0.2, 0.3]]})

    result = client.embed("bge-m3", "test text")

    assert result == [0.1, 0.2, 0.3]


def test_embed_batch(client: OllamaClient, mock_post: MagicMock) -> None:
    """embed_batch returns one vector per input, in order."""
    mock_post.return_value = make_response(
        {"embeddings": [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]}
    )

    result = client.embed_batch("bge-m3", ["a", "b", "c"])

    assert result == [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
    payload = mock_post.call_args.kwargs["json"]
    assert payload["input"] == ["a", "b", "c"]


def test_embed_batch_empty_skips_network(
    client: OllamaClient, mock_post: MagicMock
) -> None:
    """An empty batch returns [] without any HTTP call."""
    assert client.embed_batch("bge-m3", []) == []
    mock_post.assert_not_called()


def test_embed_batch_is_traced(
    client: OllamaClient, mock_post: MagicMock, tracer: object
) -> None:
    """Every batch emits an embed trace record carrying batch_size."""
    mock_post.return_value = make_response({"embeddings": [[0.1], [0.2]]})

    client.embed_batch("bge-m3", ["x", "y"])

    records = client.tracer.read_all()  # type: ignore[attr-defined]
    embed_records = [r for r in records if r.call_type == "embed"]
    assert embed_records
    assert embed_records[-1].extra["batch_size"] == 2


def test_connection_error_translated(
    client: OllamaClient, mock_post: MagicMock
) -> None:
    """A requests ConnectionError surfaces as OllamaConnectionError."""
    import requests

    mock_post.side_effect = requests.exceptions.ConnectionError("refused")

    with pytest.raises(OllamaConnectionError):
        client.chat("m", [{"role": "user", "content": "x"}])


def test_timeout_translated(client: OllamaClient, mock_post: MagicMock) -> None:
    """A requests Timeout surfaces as OllamaTimeoutError."""
    import requests

    mock_post.side_effect = requests.exceptions.ReadTimeout("slow")

    with pytest.raises(OllamaTimeoutError):
        client.chat("m", [{"role": "user", "content": "x"}])


def test_non_localhost_host_rejected() -> None:
    """Constructing with a non-loopback host raises ValueError."""
    with pytest.raises(ValueError, match="loopback"):
        OllamaClient(host="http://evil.example.com:11434")


def test_loopback_variants_accepted() -> None:
    """127.0.0.1 and localhost are both accepted."""
    assert OllamaClient(host="http://127.0.0.1:11434").host.endswith("11434")
    assert OllamaClient(host="http://localhost:11434").host.endswith("11434")


# ---------------------------------------------------------------------------
# Model failover
#
# A model that is not pulled, is corrupt, or dies under memory pressure fails
# on every request. The fallback lives on the client rather than at one call
# site, because structured() is the single choke point every LLM request in
# the codebase goes through — the router, intake, planner, critic, red team
# and meeting extraction all reach Ollama here.
# ---------------------------------------------------------------------------


def _health(client: OllamaClient, available: bool, models: list[str]) -> None:
    """Pin the client's view of what Ollama has installed."""
    client._probe_tags = lambda: {  # type: ignore[method-assign]
        "available": available,
        "models": models,
        "error": None if available else "connection refused",
    }


def test_chat_falls_back_to_another_installed_model(
    client: OllamaClient, mock_post: MagicMock
) -> None:
    _health(client, True, ["dead:1b", "alive:1b"])
    mock_post.side_effect = [
        requests.exceptions.ConnectionError("boom"),
        make_response({"message": {"content": "second model answered"}}),
    ]

    assert client.chat("dead:1b", [{"role": "user", "content": "Hi"}]) == (
        "second model answered"
    )


def test_structured_falls_back_to_another_installed_model(
    client: OllamaClient, mock_post: MagicMock
) -> None:
    _health(client, True, ["dead:1b", "alive:1b"])
    mock_post.side_effect = [
        requests.exceptions.ConnectionError("boom"),
        make_response({"message": {"content": '{"name": "ok", "value": 1}'}}),
    ]

    result = client.structured("dead:1b", [{"role": "user", "content": "Hi"}], SampleModel)

    assert result.name == "ok"


def test_no_fallback_when_ollama_itself_is_unreachable(
    client: OllamaClient, mock_post: MagicMock
) -> None:
    """Every model is behind the same daemon; retrying each buries the cause."""
    _health(client, False, [])
    mock_post.side_effect = requests.exceptions.ConnectionError("boom")

    with pytest.raises(OllamaConnectionError):
        client.chat("dead:1b", [{"role": "user", "content": "Hi"}])

    assert mock_post.call_count == 1


def test_no_fallback_when_nothing_else_is_installed(
    client: OllamaClient, mock_post: MagicMock
) -> None:
    _health(client, True, ["dead:1b"])
    mock_post.side_effect = requests.exceptions.ConnectionError("boom")

    with pytest.raises(OllamaConnectionError):
        client.chat("dead:1b", [{"role": "user", "content": "Hi"}])


def test_the_original_error_survives_when_every_model_fails(
    client: OllamaClient, mock_post: MagicMock
) -> None:
    """The message must name the model the caller asked for."""
    _health(client, True, ["dead:1b", "alsodead:1b"])
    mock_post.side_effect = requests.exceptions.ReadTimeout("slow")

    with pytest.raises(OllamaTimeoutError) as excinfo:
        client.chat("dead:1b", [{"role": "user", "content": "Hi"}])

    assert "Timed out reading" in str(excinfo.value)


def test_a_schema_failure_is_never_retried_on_another_model(
    client: OllamaClient, mock_post: MagicMock
) -> None:
    """That is a prompt or schema problem, not reachability.

    Burning through every installed model would hide it behind a slow,
    confusing failure.
    """
    _health(client, True, ["dead:1b", "alive:1b", "third:1b"])
    mock_post.return_value = make_response({"message": {"content": "not json at all"}})

    with pytest.raises(OllamaValidationError):
        client.structured(
            "m", [{"role": "user", "content": "Hi"}], SampleModel, max_retries=0
        )

    # One attempt only — no candidate models were tried.
    assert mock_post.call_count == 1


def test_allow_fallback_false_reraises_immediately(
    client: OllamaClient, mock_post: MagicMock
) -> None:
    """Panel judging opts out: which model answered is part of the result."""
    _health(client, True, ["dead:1b", "alive:1b"])
    mock_post.side_effect = requests.exceptions.ConnectionError("boom")

    with pytest.raises(OllamaConnectionError):
        client.chat(
            "dead:1b", [{"role": "user", "content": "Hi"}], allow_fallback=False
        )

    assert mock_post.call_count == 1


def test_candidate_order_is_reproducible(client: OllamaClient) -> None:
    """Which model is picked must not depend on Ollama's listing order."""
    _health(client, True, ["zz:9b", "dead:1b", "aa:9b"])

    assert client._failover_candidates("dead:1b") == ["aa:9b", "zz:9b"]


def test_failover_writes_no_probe_record_into_the_trace(
    client: OllamaClient, mock_post: MagicMock, tracer
) -> None:
    """The trace holds model calls only — one per attempt, no probe.

    The tracer is the log of model calls the caller made. Routing the
    candidate lookup through the traced health() added a record per failure,
    which the hung-Ollama fault simulation caught by asserting a single
    record. Two chat records here (the original and the one retry) are the
    two real attempts; a third entry would be the probe leaking back in.
    """
    client._probe_tags = lambda: {  # type: ignore[method-assign]
        "available": True, "models": ["dead:1b", "alive:1b"], "error": None,
    }
    mock_post.side_effect = requests.exceptions.ReadTimeout("hang")

    with pytest.raises(OllamaTimeoutError):
        client.chat("dead:1b", [{"role": "user", "content": "Hi"}])

    assert [r.call_type for r in tracer.read_all()] == ["chat", "chat"]
