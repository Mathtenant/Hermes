"""Chunking tests (offline, deterministic)."""

import pytest

from hermes_assistant.rag.chunking import Chunk, chunk_document, count_tokens


def test_count_tokens_is_word_count() -> None:
    assert count_tokens("one two three") == 3
    assert count_tokens("  spaced   out  ") == 2
    assert count_tokens("") == 0


def test_empty_document_yields_no_chunks() -> None:
    assert chunk_document("") == []
    assert chunk_document("   \n  \n") == []


def test_headings_produce_heading_paths() -> None:
    """Nested headings build a breadcrumb path on each chunk."""
    text = "# A\nintro\n## B\nbody of b\n## C\nbody of c"
    chunks = chunk_document(text)
    headings = [c.heading for c in chunks]
    assert "A" in headings
    assert "A > B" in headings
    assert "A > C" in headings


def test_deeper_then_shallower_heading_pops_stack() -> None:
    """A shallower heading pops deeper siblings from the breadcrumb."""
    text = "# A\n## B\ntext\n# D\nother"
    chunks = chunk_document(text)
    paths = {c.heading for c in chunks}
    assert "A > B" in paths
    assert "D" in paths  # not "A > B > D"


def test_indices_are_sequential_and_zero_based() -> None:
    text = "# H1\nalpha\n# H2\nbeta\n# H3\ngamma"
    chunks = chunk_document(text)
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_long_section_windows_with_overlap() -> None:
    """A section longer than the window splits with token overlap."""
    body = " ".join(f"w{i}" for i in range(100))
    text = f"# Big\n{body}"
    chunks = chunk_document(text, chunk_size_tokens=40, overlap_tokens=10)
    assert len(chunks) > 1
    # Every window carries the section heading.
    assert all(c.heading == "Big" for c in chunks)
    # Consecutive windows overlap: last 10 tokens of chunk 0 reappear in chunk 1.
    first_words = chunks[0].text.split()
    second_words = chunks[1].text.split()
    assert first_words[-10:] == second_words[:10]
    assert all(c.token_count <= 40 for c in chunks)


def test_chunking_is_deterministic() -> None:
    text = "# A\n" + " ".join(f"t{i}" for i in range(300))
    a = chunk_document(text, chunk_size_tokens=64, overlap_tokens=8)
    b = chunk_document(text, chunk_size_tokens=64, overlap_tokens=8)
    assert [(c.text, c.index, c.heading) for c in a] == [
        (c.text, c.index, c.heading) for c in b
    ]


def test_text_before_first_heading_has_no_heading() -> None:
    chunks = chunk_document("preamble text here\n# Later\nmore")
    assert chunks[0].heading is None
    assert isinstance(chunks[0], Chunk)


def test_invalid_overlap_raises() -> None:
    with pytest.raises(ValueError):
        chunk_document("x", chunk_size_tokens=10, overlap_tokens=10)
    with pytest.raises(ValueError):
        chunk_document("x", chunk_size_tokens=0)
