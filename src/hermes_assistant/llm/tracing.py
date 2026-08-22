"""Traceability logging for LLM calls.

Every model invocation MUST produce a :class:`TraceRecord`, appended as one
line of JSON to a local JSONL file. This is the audit log required by the
project contract (model id, mode, prompt hash, latency, token counts). No
database, no network — a plain local file.

Size-based rotation
-------------------
When the active trace file would exceed ``max_mb`` megabytes after a write,
the writer rotates it first: the active file is renamed to ``<path>.1``, any
existing ``<path>.1`` becomes ``<path>.2``, and so on up to ``_MAX_ROTATED``
(5) backups.  Rotation uses :func:`os.rename` which is atomic on POSIX, and
the entire check-rotate-write sequence is guarded by a :class:`threading.Lock`
so concurrent worker threads never interleave.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# Number of rotated backups kept alongside the active file (.1 … .5).
_MAX_ROTATED: int = 5


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

    Parameters
    ----------
    path:
        Destination JSONL file.  ``None`` → no-op.
    max_mb:
        Rotate when the active file exceeds this many megabytes.  ``None``
        reads ``settings.trace_max_mb`` (default 50).  Pass ``0`` to disable
        rotation entirely.
    """

    def __init__(
        self, path: str | Path | None, max_mb: int | float | None = None
    ) -> None:
        self.path: Path | None = Path(path) if path is not None else None
        if max_mb is None:
            # Late import avoids a module-level circular dependency risk and
            # keeps the default lazy so tests can monkeypatch settings freely.
            from hermes_assistant.config import settings  # noqa: PLC0415

            max_mb = settings.trace_max_mb
        # Convert MB → bytes (float-safe for sub-MB caps in tests).
        # 0 means "no rotation" (disabled).
        self._max_bytes: float = max_mb * 1024 * 1024
        self._lock = threading.Lock()

    # ---------------------------------------------------------------------- #
    # Internal helpers
    # ---------------------------------------------------------------------- #

    def _rotate(self) -> None:
        """Shift numbered backups and rename the active file to ``.1``.

        Keeps at most ``_MAX_ROTATED`` (5) rotated files.  The oldest is
        removed to make room.  Each :func:`os.rename` call is atomic on POSIX.
        Called only while ``self._lock`` is held.
        """
        assert self.path is not None  # guard: only called when path is set

        # Drop the oldest backup to bound disk usage.
        oldest = Path(f"{self.path}.{_MAX_ROTATED}")
        if oldest.exists():
            oldest.unlink()

        # Shift .4 → .5, .3 → .4, …, .1 → .2 (skips missing gaps silently).
        for n in range(_MAX_ROTATED - 1, 0, -1):
            src = Path(f"{self.path}.{n}")
            dst = Path(f"{self.path}.{n + 1}")
            if src.exists():
                os.rename(src, dst)

        # Rename the active file to .1 (atomic on POSIX).
        os.rename(self.path, Path(f"{self.path}.1"))

    # ---------------------------------------------------------------------- #
    # Public API
    # ---------------------------------------------------------------------- #

    def record(self, record: TraceRecord) -> None:
        """Append one record. Never raises into the caller's hot path."""
        if self.path is None:
            return
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            line = record.model_dump_json() + "\n"
            # Rotate before writing if this write would push us over the cap.
            # Rotation is skipped when max_bytes==0 (disabled) or when the
            # file does not yet exist (nothing to rotate).
            if (
                self._max_bytes > 0
                and self.path.exists()
                and self.path.stat().st_size + len(line.encode("utf-8"))
                > self._max_bytes
            ):
                self._rotate()
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line)

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
