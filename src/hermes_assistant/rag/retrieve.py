"""Dense retrieval over the HERMES corpus (Phase 1 section 4).

Dense-only, top-k nearest-neighbour search: embed the query with the same local
model used at ingest, then ask Chroma for the closest chunks. Optional project
scoping is a metadata filter (``project`` tag written at ingest time). Sparse /
hybrid retrieval is deferred to a later phase.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hermes_assistant.config import settings
from hermes_assistant.llm.client import OllamaClient
from hermes_assistant.rag.store import ChromaStore


@dataclass(frozen=True)
class RetrievedChunk:
    """A retrieved chunk with its similarity score and provenance."""

    id: str
    text: str
    score: float  # cosine similarity in [0, 1]; higher is more relevant.
    source: str
    heading: str | None
    metadata: dict[str, Any]


class Retriever:
    """Embed a query and return the top-k nearest corpus chunks."""

    def __init__(
        self,
        store: ChromaStore,
        client: OllamaClient,
        *,
        embed_model: str | None = None,
        top_k: int | None = None,
    ) -> None:
        self.store = store
        self.client = client
        self.embed_model = embed_model or settings.rag_embed_model
        self.top_k = top_k or settings.rag_top_k

    def retrieve(
        self,
        query: str,
        *,
        top_k: int | None = None,
        project: str | None = None,
        min_score: float | None = None,
    ) -> list[RetrievedChunk]:
        """Return the most relevant chunks for ``query``.

        Args:
            query: Natural-language query.
            top_k: Override the configured fan-out for this call.
            project: If set, restrict results to chunks tagged with this
                project (exact metadata match).
            min_score: If set, drop hits with a similarity below this floor.

        Returns:
            Up to ``top_k`` :class:`RetrievedChunk`, highest score first.
            Empty query text returns an empty list without touching Ollama.
        """
        if not query.strip():
            return []
        k = top_k or self.top_k
        where = {"project": project} if project else None

        embedding = self.client.embed(self.embed_model, query)
        hits = self.store.query(embedding, k, where=where)

        results = [
            RetrievedChunk(
                id=hit.id,
                text=hit.text,
                score=hit.score,
                source=str(hit.metadata.get("source", "")),
                heading=(hit.metadata.get("heading") or None),
                metadata=hit.metadata,
            )
            for hit in hits
        ]
        if min_score is not None:
            results = [r for r in results if r.score >= min_score]
        return results
