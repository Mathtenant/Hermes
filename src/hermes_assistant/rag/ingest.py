"""Ingestion pipeline: parse -> chunk -> embed -> store, idempotently.

Idempotency model (Phase 1 sections 3 & 6):

* A document's identity is the SHA-256 of its parsed text (``doc_hash``).
* Each chunk's ID is ``sha256(doc_hash + ":" + chunk_index)[:32]`` — fully
  deterministic, so the same file always yields the same IDs.
* Before inserting, we look up existing chunks for that ``source``:
  - same ``doc_hash``  -> **skip** (nothing changed).
  - different ``doc_hash`` -> **delete-by-source, then insert** (edited file;
    purge stale chunks so no orphans survive a content change).
  - none present -> **insert**.

Per-file error isolation: a parse/embed/store failure on one file is caught,
recorded, and ingestion continues with the next file. One bad PDF never aborts
a directory run.

Embeddings come from local Ollama via :meth:`OllamaClient.embed_batch`, so
every vector is traced automatically.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from hermes_assistant.config import settings
from hermes_assistant.llm.client import OllamaClient
from hermes_assistant.rag.chunking import chunk_document
from hermes_assistant.rag.parsers import (
    SUPPORTED_SUFFIXES,
    parse_file,
)
from hermes_assistant.rag.store import ChromaStore

logger = logging.getLogger(__name__)


class IngestStatus(str, Enum):
    """Outcome of ingesting a single file."""

    ADDED = "added"  # new document, chunks inserted
    UPDATED = "updated"  # content changed, stale chunks replaced
    SKIPPED = "skipped"  # identical content already present (idempotent)
    EMPTY = "empty"  # parsed to no chunks (blank / unreadable)
    FAILED = "failed"  # parse/embed/store error (isolated)


@dataclass
class FileResult:
    """Per-file ingestion result."""

    source: str
    status: IngestStatus
    chunks: int = 0
    error: str | None = None


@dataclass
class IngestReport:
    """Aggregate result of an ingest run over one or more files."""

    results: list[FileResult] = field(default_factory=list)

    @property
    def chunks_added(self) -> int:
        return sum(r.chunks for r in self.results if r.status in _WROTE)

    @property
    def files_added(self) -> int:
        return sum(1 for r in self.results if r.status is IngestStatus.ADDED)

    @property
    def files_updated(self) -> int:
        return sum(1 for r in self.results if r.status is IngestStatus.UPDATED)

    @property
    def files_skipped(self) -> int:
        return sum(1 for r in self.results if r.status is IngestStatus.SKIPPED)

    @property
    def files_failed(self) -> int:
        return sum(1 for r in self.results if r.status is IngestStatus.FAILED)


_WROTE = (IngestStatus.ADDED, IngestStatus.UPDATED)


def compute_doc_hash(text: str) -> str:
    """SHA-256 of the parsed document text (the document's identity)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_id(doc_hash: str, chunk_index: int) -> str:
    """Deterministic 32-char chunk ID from doc hash + index."""
    return hashlib.sha256(f"{doc_hash}:{chunk_index}".encode()).hexdigest()[:32]


def _existing_doc_hash(store: ChromaStore, source: str) -> str | None:
    """Return the stored ``doc_hash`` for ``source``, or ``None`` if absent."""
    existing = store.get_by_source(source)
    if not existing:
        return None
    return str(existing[0].metadata.get("doc_hash", "")) or None


def _embed_all(
    client: OllamaClient,
    model: str,
    texts: list[str],
    batch_size: int,
) -> list[list[float]]:
    """Embed ``texts`` in batches, preserving order."""
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        vectors.extend(client.embed_batch(model, batch))
    return vectors


def ingest_file(
    store: ChromaStore,
    client: OllamaClient,
    path: str | Path,
    *,
    project: str | None = None,
    chunk_size_tokens: int | None = None,
    overlap_tokens: int | None = None,
    embed_model: str | None = None,
    embed_batch_size: int | None = None,
) -> FileResult:
    """Ingest a single file. Never raises — failures become FAILED results."""
    source = str(Path(path).resolve())
    chunk_size = chunk_size_tokens or settings.rag_chunk_size_tokens
    overlap = overlap_tokens if overlap_tokens is not None else settings.rag_chunk_overlap_tokens
    model = embed_model or settings.rag_embed_model
    batch_size = embed_batch_size or settings.rag_embed_batch_size

    try:
        text = parse_file(path)
        chunks = chunk_document(
            text, chunk_size_tokens=chunk_size, overlap_tokens=overlap
        )
        if not chunks:
            return FileResult(source=source, status=IngestStatus.EMPTY)

        doc_hash = compute_doc_hash(text)
        prior = _existing_doc_hash(store, source)
        if prior == doc_hash:
            return FileResult(
                source=source, status=IngestStatus.SKIPPED, chunks=len(chunks)
            )

        # Edited file: purge stale chunks before re-inserting.
        status = IngestStatus.ADDED
        if prior is not None:
            store.delete_by_source(source)
            status = IngestStatus.UPDATED

        ingested_at = datetime.now(UTC).isoformat()
        ids = [chunk_id(doc_hash, c.index) for c in chunks]
        documents = [c.text for c in chunks]
        metadatas: list[dict[str, Any]] = [
            {
                "source": source,
                "doc_hash": doc_hash,
                "chunk_index": c.index,
                "heading": c.heading or "",
                "token_count": c.token_count,
                "project": project or "",
                "ingested_at": ingested_at,
            }
            for c in chunks
        ]
        embeddings = _embed_all(client, model, documents, batch_size)
        if len(embeddings) != len(documents):
            raise RuntimeError(
                f"embed_batch returned {len(embeddings)} vectors for"
                f" {len(documents)} documents — embedding count mismatch"
            )
        store.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)
        return FileResult(source=source, status=status, chunks=len(chunks))
    except Exception as exc:  # noqa: BLE001 — per-file isolation is intentional.
        logger.warning("Ingest failed for %s: %s", source, exc)
        return FileResult(source=source, status=IngestStatus.FAILED, error=str(exc))


def _iter_files(path: Path) -> list[Path]:
    """Return the file(s) under ``path`` with a supported extension."""
    if path.is_file():
        return [path]
    return sorted(
        p
        for p in path.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
    )


def ingest_path(
    store: ChromaStore,
    client: OllamaClient,
    path: str | Path,
    *,
    project: str | None = None,
    chunk_size_tokens: int | None = None,
    overlap_tokens: int | None = None,
    embed_model: str | None = None,
    embed_batch_size: int | None = None,
) -> IngestReport:
    """Ingest a file or (recursively) a directory of supported files.

    Args:
        store: Target ChromaStore.
        client: Ollama client for embeddings.
        path: File or directory to ingest.
        project: Optional project tag stored on every chunk for later filtering.
        chunk_size_tokens / overlap_tokens: Chunk geometry overrides.
        embed_model / embed_batch_size: Embedding overrides.

    Returns:
        An :class:`IngestReport` with a per-file result. Files that fail are
        recorded as FAILED; the run always completes.

    Raises:
        FileNotFoundError: If ``path`` does not exist at all.
    """
    root = Path(path)
    if not root.exists():
        raise FileNotFoundError(f"No such path: {root}")

    report = IngestReport()
    for file_path in _iter_files(root):
        report.results.append(
            ingest_file(
                store,
                client,
                file_path,
                project=project,
                chunk_size_tokens=chunk_size_tokens,
                overlap_tokens=overlap_tokens,
                embed_model=embed_model,
                embed_batch_size=embed_batch_size,
            )
        )
    return report
