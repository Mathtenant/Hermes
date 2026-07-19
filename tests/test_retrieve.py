"""Retriever tests: ranking, score floor, project filtering (AC1, offline)."""

from pathlib import Path

from hermes_assistant.rag.ingest import ingest_file
from hermes_assistant.rag.retrieve import Retriever
from hermes_assistant.rag.store import ChromaStore

from .conftest import FakeEmbedder


def _seed_topic_corpus(store: ChromaStore, embedder: FakeEmbedder) -> None:
    """Three short, well-separated documents for deterministic ranking."""
    docs = {
        "phases": "HERMES phases Initialisierung Konzept Realisierung Einfuehrung",
        "roles": "HERMES roles Auftraggeber Projektleiter Anwender",
        "outcomes": "HERMES outcomes Studie Schutzbedarfsanalyse Projektauftrag",
    }
    ids = list(docs)
    store.add(
        ids=ids,
        embeddings=embedder.embed_batch("bge-m3", list(docs.values())),
        documents=list(docs.values()),
        metadatas=[{"source": f"/f/{k}.md", "project": "hermes"} for k in ids],
    )


def test_ac1_top_chunk_relevant_with_high_score(
    store: ChromaStore, fake_embedder: FakeEmbedder
) -> None:
    """[AC1] A known query returns the relevant chunk on top with score > 0.5."""
    _seed_topic_corpus(store, fake_embedder)
    retriever = Retriever(store, fake_embedder, top_k=3)

    hits = retriever.retrieve("HERMES phases Initialisierung Konzept Realisierung")

    assert hits[0].id == "phases"
    assert hits[0].score > 0.5
    assert hits[0].score > hits[1].score  # clearly outranks the others


def test_retrieve_respects_top_k(
    store: ChromaStore, fake_embedder: FakeEmbedder
) -> None:
    _seed_topic_corpus(store, fake_embedder)
    retriever = Retriever(store, fake_embedder, top_k=5)
    assert len(retriever.retrieve("HERMES", top_k=2)) == 2


def test_min_score_floor_drops_weak_hits(
    store: ChromaStore, fake_embedder: FakeEmbedder
) -> None:
    _seed_topic_corpus(store, fake_embedder)
    retriever = Retriever(store, fake_embedder, top_k=3)
    hits = retriever.retrieve(
        "HERMES phases Initialisierung Konzept Realisierung", min_score=0.5
    )
    assert hits  # the phases chunk clears the floor
    assert all(h.score >= 0.5 for h in hits)


def test_project_filter_scopes_results(
    store: ChromaStore, fake_embedder: FakeEmbedder
) -> None:
    """Project scoping restricts results to matching-tagged chunks."""
    store.add(
        ids=["p1", "p2"],
        embeddings=fake_embedder.embed_batch("bge-m3", ["alpha text", "beta text"]),
        documents=["alpha text", "beta text"],
        metadatas=[
            {"source": "/a.md", "project": "alpha"},
            {"source": "/b.md", "project": "beta"},
        ],
    )
    retriever = Retriever(store, fake_embedder, top_k=5)
    hits = retriever.retrieve("text", project="beta")
    assert [h.id for h in hits] == ["p2"]
    assert hits[0].metadata["project"] == "beta"


def test_empty_query_returns_empty_without_embedding(
    store: ChromaStore, fake_embedder: FakeEmbedder
) -> None:
    retriever = Retriever(store, fake_embedder)
    assert retriever.retrieve("   ") == []
    assert fake_embedder.embed_calls == []  # never touched the embedder


def test_retrieve_after_full_ingest_ranks_by_heading(
    store: ChromaStore, fake_embedder: FakeEmbedder, sample_md: Path
) -> None:
    """End-to-end: ingest the sample doc, then a roles query surfaces Roles."""
    ingest_file(store, fake_embedder, sample_md)
    retriever = Retriever(store, fake_embedder, top_k=3)

    hits = retriever.retrieve("Auftraggeber Projektleiter Anwender roles")

    assert hits
    assert hits[0].heading is not None
    assert "Roles" in hits[0].heading
