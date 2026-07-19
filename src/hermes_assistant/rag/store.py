"""ChromaDB persistence wrapper for the HERMES corpus.

Design invariants (Phase 1 sections 2 & 7):

* **Single collection** for the whole corpus. A per-embedding-model split is a
  Phase 2 concern; the collection name is a config knob so that hook is cheap.
* **``embedding_function=None`` is mandatory.** We supply pre-computed vectors
  from local Ollama/bge-m3. If Chroma were allowed to keep its default embedder
  it would try to *download* an ONNX model on first use — a silent network
  call that violates the no-cloud contract. Passing ``None`` disables that.
* **Cosine space** (``hnsw:space=cosine``) so retrieval scores map cleanly to
  ``1 - distance`` in ``[0, 1]``.

The wrapper is intentionally thin: add / query / get / delete-by-source /
count. All embedding and dedup logic lives in :mod:`rag.ingest`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb


@dataclass(frozen=True)
class StoredChunk:
    """A chunk read back out of the store."""

    id: str
    text: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class QueryHit:
    """One nearest-neighbour result with a normalised similarity score."""

    id: str
    text: str
    metadata: dict[str, Any]
    score: float  # cosine similarity in [0, 1]; higher is closer.


class ChromaStore:
    """Persistent Chroma collection holding pre-embedded corpus chunks."""

    def __init__(
        self,
        path: str | Path,
        collection_name: str,
        *,
        distance: str = "cosine",
    ) -> None:
        """Open (or create) a persistent collection.

        Args:
            path: On-disk directory for the Chroma database.
            collection_name: Single-corpus collection name.
            distance: HNSW space; ``cosine`` keeps scores in ``[0, 1]``.
        """
        Path(path).mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(path))
        # CRITICAL: embedding_function=None -> no default model, no download.
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=None,
            metadata={"hnsw:space": distance},
        )

    def add(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        """Upsert chunks with pre-computed embeddings."""
        if not ids:
            return
        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

    def query(
        self,
        embedding: list[float],
        n_results: int,
        *,
        where: dict[str, Any] | None = None,
    ) -> list[QueryHit]:
        """Return the ``n_results`` nearest chunks to ``embedding``.

        ``where`` is an optional Chroma metadata filter (e.g. project scoping).
        Cosine distance is converted to a ``1 - distance`` similarity score.
        """
        result = self.collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        hits: list[QueryHit] = []
        ids = result["ids"][0]
        docs = result["documents"][0]
        metas = result["metadatas"][0]
        dists = result["distances"][0]
        for cid, doc, meta, dist in zip(ids, docs, metas, dists, strict=True):
            hits.append(
                QueryHit(
                    id=cid,
                    text=doc,
                    metadata=dict(meta or {}),
                    score=1.0 - float(dist),
                )
            )
        return hits

    def get_by_id(self, chunk_id: str) -> StoredChunk | None:
        """Fetch a single chunk by its ID, or ``None`` if absent."""
        result = self.collection.get(
            ids=[chunk_id], include=["documents", "metadatas"]
        )
        if not result["ids"]:
            return None
        return StoredChunk(
            id=result["ids"][0],
            text=result["documents"][0],
            metadata=dict(result["metadatas"][0] or {}),
        )

    def get_by_source(self, source: str) -> list[StoredChunk]:
        """Fetch all chunks originating from ``source`` (a file path)."""
        result = self.collection.get(
            where={"source": source}, include=["documents", "metadatas"]
        )
        return [
            StoredChunk(id=cid, text=doc, metadata=dict(meta or {}))
            for cid, doc, meta in zip(
                result["ids"],
                result["documents"],
                result["metadatas"],
                strict=True,
            )
        ]

    def delete_by_source(self, source: str) -> None:
        """Delete every chunk whose ``source`` metadata equals ``source``.

        Used to purge stale chunks before re-ingesting an edited file so no
        orphaned vectors survive a content change.
        """
        self.collection.delete(where={"source": source})

    def count(self) -> int:
        """Total number of chunks in the collection."""
        return int(self.collection.count())
