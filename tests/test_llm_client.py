"""Tests for OllamaClient (mocked Ollama, fully offline)."""

from unittest.mock import MagicMock

import pytest
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
