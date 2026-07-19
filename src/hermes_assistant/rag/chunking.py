"""Heading-aware document chunking with token overlap.

Strategy (Phase 1 design section 1):

1. Split the document on Markdown headings (``#`` .. ``######``). Each section
   inherits a *heading path* (e.g. ``"Phases > Initialisierung"``) so a chunk
   always knows where it came from.
2. Within a section, pack text into windows of ``chunk_size_tokens`` with a
   trailing ``overlap_tokens`` carry-over into the next window, so context
   isn't severed at a boundary.

Tokens are approximated by whitespace-delimited words. That's deliberately
model-agnostic: we don't ship a tokenizer, and word count tracks bge-m3's
subword count closely enough for chunk sizing. Chunking is fully deterministic,
which is what makes ingestion idempotent (see rag/ingest.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# A Markdown ATX heading: 1-6 '#', a space, then the heading text.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


@dataclass(frozen=True)
class Chunk:
    """One retrievable unit of text with its provenance."""

    text: str
    index: int
    token_count: int
    heading: str | None = None


@dataclass
class _Section:
    """An intermediate heading-delimited block of body lines."""

    heading_path: str | None
    lines: list[str] = field(default_factory=list)


def count_tokens(text: str) -> int:
    """Approximate token count as the number of whitespace-delimited words."""
    return len(text.split())


def _split_sections(text: str) -> list[_Section]:
    """Break ``text`` into heading-delimited sections, tracking heading paths."""
    sections: list[_Section] = []
    # Stack of (level, title) for building the breadcrumb heading path.
    heading_stack: list[tuple[int, str]] = []
    current = _Section(heading_path=None)

    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            # Close the current section before starting a new one.
            if current.lines:
                sections.append(current)
            level = len(match.group(1))
            title = match.group(2).strip()
            # Pop sibling/deeper headings, then push this one.
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
            path = " > ".join(t for _, t in heading_stack)
            current = _Section(heading_path=path)
        else:
            current.lines.append(line)

    if current.lines:
        sections.append(current)
    return sections


def _window(
    words: list[str], size: int, overlap: int
) -> list[list[str]]:
    """Slide a ``size``-word window with ``overlap`` carry-over."""
    if len(words) <= size:
        return [words]
    step = max(1, size - overlap)
    windows: list[list[str]] = []
    start = 0
    while start < len(words):
        windows.append(words[start : start + size])
        if start + size >= len(words):
            break
        start += step
    return windows


def chunk_document(
    text: str,
    *,
    chunk_size_tokens: int = 512,
    overlap_tokens: int = 64,
) -> list[Chunk]:
    """Chunk ``text`` into heading-aware, overlapping windows.

    Args:
        text: Normalised document text (Markdown headings respected).
        chunk_size_tokens: Target window size in ~word tokens.
        overlap_tokens: Tokens carried from one window into the next.

    Returns:
        Deterministic list of :class:`Chunk`, indexed from 0. Empty input
        (or whitespace-only) yields an empty list.

    Raises:
        ValueError: If ``overlap_tokens`` >= ``chunk_size_tokens`` or either
            is negative.
    """
    if chunk_size_tokens <= 0:
        raise ValueError("chunk_size_tokens must be positive")
    if overlap_tokens < 0:
        raise ValueError("overlap_tokens must be non-negative")
    if overlap_tokens >= chunk_size_tokens:
        raise ValueError("overlap_tokens must be smaller than chunk_size_tokens")

    chunks: list[Chunk] = []
    index = 0
    for section in _split_sections(text):
        body = "\n".join(section.lines).strip()
        if not body:
            continue
        words = body.split()
        for window in _window(words, chunk_size_tokens, overlap_tokens):
            chunk_text = " ".join(window)
            chunks.append(
                Chunk(
                    text=chunk_text,
                    index=index,
                    token_count=len(window),
                    heading=section.heading_path,
                )
            )
            index += 1
    return chunks
