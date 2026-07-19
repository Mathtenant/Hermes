"""Ingest pipeline tests: idempotency (AC2), dedup, error isolation."""

from pathlib import Path

from hermes_assistant.rag.ingest import (
    IngestStatus,
    chunk_id,
    compute_doc_hash,
    ingest_file,
    ingest_path,
)
from hermes_assistant.rag.store import ChromaStore

from .conftest import FakeEmbedder


def test_chunk_id_is_deterministic_and_32_chars() -> None:
    h = compute_doc_hash("some text")
    cid = chunk_id(h, 3)
    assert cid == chunk_id(h, 3)
    assert len(cid) == 32
    assert chunk_id(h, 3) != chunk_id(h, 4)


def test_ingest_file_adds_chunks(
    store: ChromaStore, fake_embedder: FakeEmbedder, sample_md: Path
) -> None:
    result = ingest_file(store, fake_embedder, sample_md)
    assert result.status is IngestStatus.ADDED
    assert result.chunks > 0
    assert store.count() == result.chunks
    # Every chunk was embedded via the batched path.
    assert sum(fake_embedder.batch_calls) == result.chunks


def test_reingest_is_idempotent(
    store: ChromaStore, fake_embedder: FakeEmbedder, sample_md: Path
) -> None:
    """[AC2] Re-ingesting an unchanged file adds nothing and does not duplicate."""
    first = ingest_file(store, fake_embedder, sample_md)
    count_after_first = store.count()

    second = ingest_file(store, fake_embedder, sample_md)

    assert first.status is IngestStatus.ADDED
    assert second.status is IngestStatus.SKIPPED
    assert store.count() == count_after_first  # unchanged — no duplication


def test_edited_file_replaces_stale_chunks(
    store: ChromaStore, fake_embedder: FakeEmbedder, tmp_path: Path
) -> None:
    """An edited file purges old chunks (delete-by-source) before re-inserting."""
    doc = tmp_path / "edit.md"
    doc.write_text("# A\none two three four five", encoding="utf-8")
    ingest_file(store, fake_embedder, doc)
    source = str(doc.resolve())
    old_ids = {c.id for c in store.get_by_source(source)}

    doc.write_text("# A\ncompletely different content now", encoding="utf-8")
    result = ingest_file(store, fake_embedder, doc)

    assert result.status is IngestStatus.UPDATED
    new_ids = {c.id for c in store.get_by_source(source)}
    assert new_ids != old_ids
    # No stale chunk survives: every stored chunk carries the new doc hash.
    new_hash = compute_doc_hash("# A\ncompletely different content now")
    assert all(
        c.metadata["doc_hash"] == new_hash for c in store.get_by_source(source)
    )


def test_metadata_records_provenance(
    store: ChromaStore, fake_embedder: FakeEmbedder, sample_md: Path
) -> None:
    ingest_file(store, fake_embedder, sample_md, project="demo")
    chunks = store.get_by_source(str(sample_md.resolve()))
    meta = chunks[0].metadata
    assert meta["project"] == "demo"
    assert meta["source"].endswith("hermes_sample.md")
    assert "doc_hash" in meta and "heading" in meta and "token_count" in meta


def test_ingest_directory_isolates_failures(
    store: ChromaStore, fake_embedder: FakeEmbedder, tmp_path: Path
) -> None:
    """A directory run continues past a broken file (per-file isolation)."""
    (tmp_path / "good.md").write_text("# G\nhello world content", encoding="utf-8")
    # A .docx that is not a real docx -> parser raises, isolated as FAILED.
    (tmp_path / "bad.docx").write_text("not a real docx", encoding="utf-8")

    report = ingest_path(store, fake_embedder, tmp_path)

    statuses = {Path(r.source).name: r.status for r in report.results}
    assert statuses["good.md"] is IngestStatus.ADDED
    assert statuses["bad.docx"] is IngestStatus.FAILED
    assert report.files_failed == 1
    assert report.files_added == 1
    assert store.count() > 0  # the good file still landed


def test_ingest_empty_file(
    store: ChromaStore, fake_embedder: FakeEmbedder, tmp_path: Path
) -> None:
    empty = tmp_path / "empty.md"
    empty.write_text("   \n\n", encoding="utf-8")
    result = ingest_file(store, fake_embedder, empty)
    assert result.status is IngestStatus.EMPTY
    assert store.count() == 0


def test_ingest_missing_path_raises(
    store: ChromaStore, fake_embedder: FakeEmbedder, tmp_path: Path
) -> None:
    import pytest

    with pytest.raises(FileNotFoundError):
        ingest_path(store, fake_embedder, tmp_path / "nope")


def test_vector_count_mismatch_is_isolated(store: ChromaStore, tmp_path: Path) -> None:
    """embed_batch returning fewer vectors than chunks → FAILED, not silent corruption."""

    class ShortEmbedder(FakeEmbedder):
        def embed_batch(self, model: str, texts: list[str]) -> list[list[float]]:
            # Return one fewer vector than requested to trigger the mismatch guard.
            return super().embed_batch(model, texts)[:-1]

    doc = tmp_path / "test.md"
    doc.write_text("# Section\n" + " ".join(["word"] * 10), encoding="utf-8")
    result = ingest_file(store, ShortEmbedder(), doc)
    assert result.status is IngestStatus.FAILED
    assert "mismatch" in (result.error or "").lower()
    assert store.count() == 0  # nothing written to the store
