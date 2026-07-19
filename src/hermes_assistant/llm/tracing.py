"""Traceability logging for LLM calls.

Every model invocation MUST produce a :class:`TraceRecord`, appended as one
line of JSON to a local JSONL file. This is the audit log required by the
project contract (model id, mode, prompt hash, latency, token counts). No
database, no network — a plain local file.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


def hash_prompt(messages: list[dict[str, str]] | str) -> str:
    """Return a short, stable SHA-256 hash of a prompt.

    Accepts either a list of chat messages or a raw string (e.g. embed input).
    Used so the trace log can correlate identical prompts without storing the
    (potentially confidential) prompt text itself.
    """
    if isinstance(messages, str):
        payload = messages
    else:
        payload = json.dumps(messages, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class TraceRecord(BaseModel):
    """One audited LLM call."""

    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    call_type: str  # "chat" | "structured" | "embed" | "health"
    model: str
    mode: str  # "instruct" | "thinking" | "embed"
    prompt_hash: str
    latency_ms: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    success: bool = True
    error: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class JsonlTracer:
    """Append :class:`TraceRecord` rows to a JSONL file.

    If ``path`` is ``None`` the tracer is a no-op (useful in tests that do not
    assert on tracing). Otherwise the parent directory is created lazily on
    first write.
    """

    def __init__(self, path: str | Path | None) -> None:
        self.path: Path | None = Path(path) if path is not None else None

    def record(self, record: TraceRecord) -> None:
        """Append one record. Never raises into the caller's hot path."""
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(record.model_dump_json() + "\n")

    def read_all(self) -> list[TraceRecord]:
        """Read back all records (mainly for tests & audits)."""
        if self.path is None or not self.path.exists():
            return []
        records: list[TraceRecord] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(TraceRecord.model_validate_json(line))
        return records
