"""Traceability tests: every call produces a complete JSONL record."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
from pydantic import BaseModel

from hermes_assistant.llm.client import OllamaClient
from hermes_assistant.llm.tracing import JsonlTracer, TraceRecord

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


def _make_record(n: int = 0) -> TraceRecord:
    """Return a minimal TraceRecord suitable for rotation tests."""
    return TraceRecord(
        call_type="chat",
        model="qwen3:4b",
        mode="instruct",
        prompt_hash=f"deadbeef{n:08x}",
        latency_ms=1.0,
        success=True,
    )


def test_rotation_creates_backup_file(tmp_path: Path) -> None:
    """Writing past the size cap rotates active file to .1 and starts fresh.

    Strategy: ``max_mb=0.0001`` sets the cap to ~100 bytes.  A single
    TraceRecord JSON line is ~250 bytes, so the second write to an already-
    populated file always exceeds the cap and triggers rotation.
    """
    trace_file = tmp_path / "trace.jsonl"
    # ~100-byte cap → any second write to a non-empty file triggers rotation.
    tracer = JsonlTracer(trace_file, max_mb=0.0001)

    rec1 = _make_record(1)
    rec2 = _make_record(2)
    rec3 = _make_record(3)

    tracer.record(rec1)  # first write: file doesn't exist yet → no rotation
    tracer.record(rec2)  # second write: file has content → rotate → .1 created
    tracer.record(rec3)  # third write: again exceeds cap → .1 → .2, active → .1

    rotated_1 = Path(f"{trace_file}.1")
    rotated_2 = Path(f"{trace_file}.2")

    # Both backup files must exist.
    assert rotated_1.exists(), ".1 backup not created after second rotation"
    assert rotated_2.exists(), ".2 backup not created after third rotation"

    # Active file contains only the most recent record.
    active_lines = [
        ln for ln in trace_file.read_text(encoding="utf-8").splitlines() if ln
    ]
    assert len(active_lines) == 1
    active_rec = TraceRecord.model_validate_json(active_lines[0])
    assert active_rec.prompt_hash == rec3.prompt_hash

    # .1 contains rec2 (the second-most-recent rotation).
    r1_lines = [
        ln for ln in rotated_1.read_text(encoding="utf-8").splitlines() if ln
    ]
    assert len(r1_lines) == 1
    assert TraceRecord.model_validate_json(r1_lines[0]).prompt_hash == rec2.prompt_hash

    # .2 contains the original first record.
    r2_lines = [
        ln for ln in rotated_2.read_text(encoding="utf-8").splitlines() if ln
    ]
    assert len(r2_lines) == 1
    assert TraceRecord.model_validate_json(r2_lines[0]).prompt_hash == rec1.prompt_hash
