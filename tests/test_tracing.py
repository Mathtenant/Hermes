"""Traceability tests: every call produces a complete JSONL record."""

from unittest.mock import MagicMock, patch

import requests
from pydantic import BaseModel

from hermes_assistant.llm.client import OllamaClient
from hermes_assistant.llm.tracing import JsonlTracer

from .conftest import make_response

REQUIRED_FIELDS = {
    "timestamp",
    "call_type",
    "model",
    "mode",
    "prompt_hash",
    "latency_ms",
    "success",
}


def test_use_case_chat_traced(
    client: OllamaClient, tracer: JsonlTracer, mock_post: MagicMock
) -> None:
    """Use case 1: a chat call writes exactly one complete JSONL record."""
    mock_post.return_value = make_response(
        {
            "message": {"content": "hi"},
            "prompt_eval_count": 11,
            "eval_count": 4,
        }
    )

    client.chat("qwen3:4b", [{"role": "user", "content": "hello"}])

    records = tracer.read_all()
    assert len(records) == 1
    rec = records[0]
    dumped = rec.model_dump()
    assert REQUIRED_FIELDS.issubset(dumped.keys())
    assert rec.call_type == "chat"
    assert rec.model == "qwen3:4b"
    assert rec.mode == "instruct"
    assert rec.prompt_hash
    assert rec.success is True
    assert rec.prompt_tokens == 11
    assert rec.completion_tokens == 4
    assert rec.total_tokens == 15


def test_chat_think_traced_as_thinking_mode(
    client: OllamaClient, tracer: JsonlTracer, mock_post: MagicMock
) -> None:
    """think=True is recorded with mode='thinking'."""
    mock_post.return_value = make_response({"message": {"content": "x"}})
    client.chat("m", [{"role": "user", "content": "x"}], think=True)
    assert tracer.read_all()[0].mode == "thinking"


def test_use_case_structured_retry_traced_per_attempt(
    client: OllamaClient, tracer: JsonlTracer, mock_post: MagicMock
) -> None:
    """Use case 2: each structured attempt (fail then pass) is traced."""

    class Out(BaseModel):
        n: int

    mock_post.side_effect = [
        make_response({"message": {"content": "{bad}"}}),
        make_response({"message": {"content": '{"n": 5}'}}),
    ]

    client.structured("m", [{"role": "user", "content": "x"}], Out, max_retries=1)

    records = tracer.read_all()
    assert len(records) == 2
    assert records[0].success is False and records[0].extra["validation_ok"] is False
    assert records[1].success is True and records[1].extra["validation_ok"] is True


def test_embed_traced(
    client: OllamaClient, tracer: JsonlTracer, mock_post: MagicMock
) -> None:
    """Embed calls are traced with mode='embed'."""
    mock_post.return_value = make_response({"embeddings": [[0.1, 0.2]]})
    client.embed("bge-m3", "text")
    rec = tracer.read_all()[0]
    assert rec.call_type == "embed"
    assert rec.mode == "embed"


def test_failed_call_traced_with_error(
    client: OllamaClient, tracer: JsonlTracer, mock_post: MagicMock
) -> None:
    """A transport failure still produces a trace with success=False."""
    mock_post.side_effect = requests.exceptions.ConnectionError("down")
    try:
        client.chat("m", [{"role": "user", "content": "x"}])
    except Exception:
        pass
    rec = tracer.read_all()[0]
    assert rec.success is False
    assert rec.error


def test_use_case_health_unavailable_no_exception(tracer: JsonlTracer) -> None:
    """Use case 3: health() on unavailable Ollama returns a dict, no raise."""
    client = OllamaClient(host="http://localhost:11434", tracer=tracer)
    with patch(
        "hermes_assistant.llm.client.requests.get",
        side_effect=requests.exceptions.ConnectionError("refused"),
    ):
        status = client.health()

    assert status["available"] is False
    assert status["host"] == "http://localhost:11434"
    assert status["models"] == []
    assert status["error"]
    assert tracer.read_all()[0].call_type == "health"


def test_health_available(tracer: JsonlTracer) -> None:
    """health() reports available with model names when Ollama responds."""
    client = OllamaClient(host="http://localhost:11434", tracer=tracer)
    with patch(
        "hermes_assistant.llm.client.requests.get",
        return_value=make_response({"models": [{"name": "qwen3:4b"}]}),
    ):
        status = client.health()
    assert status["available"] is True
    assert status["models"] == ["qwen3:4b"]
