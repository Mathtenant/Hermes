"""End-to-end RAG integration against a live Ollama + bge-m3.

Marked ``integration`` and skipped automatically when Ollama is unreachable or
bge-m3 is not pulled, so the default offline suite stays green. Run explicitly:

    pytest -m integration

These are the *real* acceptance checks: semantic retrieval with bge-m3.
"""

from pathlib import Path

import pytest

from hermes_assistant.config import settings
from hermes_assistant.llm.client import OllamaClient
from hermes_assistant.rag.ingest import IngestStatus, ingest_file
from hermes_assistant.rag.retrieve import Retriever
from hermes_assistant.rag.store import ChromaStore

pytestmark = pytest.mark.integration


@pytest.fixture
def live_client() -> OllamaClient:
    """A real client, skipping the test if Ollama or bge-m3 is unavailable."""
    client = OllamaClient(host=settings.ollama_host)
    health = client.health()
    if not health["available"]:
        pytest.skip("Ollama service is not reachable")
    installed = {str(m).split(":")[0] for m in health["models"]}
    if settings.rag_embed_model.split(":")[0] not in installed:
        pytest.skip(f"embedding model {settings.rag_embed_model} not pulled")
    return client


def test_ac1_semantic_retrieval(
    tmp_path: Path, live_client: OllamaClient, sample_md: Path
) -> None:
    """[AC1] Ingest the sample doc; a phases query returns a relevant top chunk."""
    store = ChromaStore(tmp_path / "vs", settings.rag_collection_name)
    result = ingest_file(store, live_client, sample_md)
    assert result.status is IngestStatus.ADDED

    retriever = Retriever(store, live_client)
    hits = retriever.retrieve("What are the HERMES phases?")

    assert hits, "retrieval returned no chunks"
    top = hits[0]
    assert top.score > 0.5, f"top score {top.score} below 0.5"
    assert "phase" in top.text.lower() or (
        top.heading is not None and "phase" in top.heading.lower()
    )


def test_ac2_idempotent_reingest(
    tmp_path: Path, live_client: OllamaClient, sample_md: Path
) -> None:
    """[AC2] Re-ingesting the same file with real embeddings adds no duplicates."""
    store = ChromaStore(tmp_path / "vs", settings.rag_collection_name)
    ingest_file(store, live_client, sample_md)
    count_after_first = store.count()

    second = ingest_file(store, live_client, sample_md)

    assert second.status is IngestStatus.SKIPPED
    assert store.count() == count_after_first
