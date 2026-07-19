"""ChromaStore tests (real Chroma, temp dir, no network)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from hermes_assistant.rag.store import ChromaStore


def _add_two(store: ChromaStore) -> None:
    store.add(
        ids=["id_a", "id_b"],
        embeddings=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        documents=["alpha doc", "beta doc"],
        metadatas=[
            {"source": "/f/a.md", "doc_hash": "h1"},
            {"source": "/f/b.md", "doc_hash": "h2"},
        ],
    )


def test_embedding_function_is_none(store: ChromaStore) -> None:
    """CRITICAL: no default embedder is attached (no model download)."""
    assert store.collection._embedding_function is None


def test_store_passes_embedding_function_none(tmp_path: Path) -> None:
    """The wrapper explicitly forwards embedding_function=None to Chroma."""
    fake_client = MagicMock()
    with patch(
        "hermes_assistant.rag.store.chromadb.PersistentClient",
        return_value=fake_client,
    ):
        ChromaStore(tmp_path / "vs", "hermes_corpus")
    kwargs = fake_client.get_or_create_collection.call_args.kwargs
    assert kwargs["embedding_function"] is None
    assert kwargs["metadata"] == {"hnsw:space": "cosine"}
    assert kwargs["name"] == "hermes_corpus"


def test_add_and_count(store: ChromaStore) -> None:
    assert store.count() == 0
    _add_two(store)
    assert store.count() == 2


def test_add_empty_is_noop(store: ChromaStore) -> None:
    store.add(ids=[], embeddings=[], documents=[], metadatas=[])
    assert store.count() == 0


def test_query_returns_scored_hits(store: ChromaStore) -> None:
    _add_two(store)
    hits = store.query([1.0, 0.0, 0.0], n_results=2)
    assert hits[0].id == "id_a"  # exact match ranks first
    assert hits[0].score > 0.99  # cosine similarity ~1.0
    assert hits[0].score >= hits[1].score


def test_query_where_filter(store: ChromaStore) -> None:
    _add_two(store)
    hits = store.query([1.0, 0.0, 0.0], n_results=5, where={"source": "/f/b.md"})
    assert [h.id for h in hits] == ["id_b"]


def test_get_by_id(store: ChromaStore) -> None:
    _add_two(store)
    got = store.get_by_id("id_a")
    assert got is not None
    assert got.text == "alpha doc"
    assert got.metadata["doc_hash"] == "h1"
    assert store.get_by_id("missing") is None


def test_get_by_source(store: ChromaStore) -> None:
    _add_two(store)
    chunks = store.get_by_source("/f/a.md")
    assert [c.id for c in chunks] == ["id_a"]


def test_delete_by_source(store: ChromaStore) -> None:
    _add_two(store)
    store.delete_by_source("/f/a.md")
    assert store.count() == 1
    assert store.get_by_id("id_a") is None
    assert store.get_by_id("id_b") is not None


def test_persistence_across_instances(tmp_path: Path) -> None:
    """Data survives reopening the same on-disk path."""
    s1 = ChromaStore(tmp_path / "vs", "hermes_corpus")
    _add_two(s1)
    s2 = ChromaStore(tmp_path / "vs", "hermes_corpus")
    assert s2.count() == 2
