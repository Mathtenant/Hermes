"""Performance tests: Suggestion Store (review feedback loop) at scale.

Validates extraction, application, and comparison latencies when the
suggestion store contains large numbers of entries.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from hermes_assistant.suggestions.store import SuggestionStore


@pytest.fixture()
def store(tmp_path: Path) -> SuggestionStore:
    return SuggestionStore(tmp_path / "sugg_perf.db")


def test_suggestions_50_extract_under_50ms(store: SuggestionStore) -> None:
    """Inserting and listing 50 suggestions finishes in under 50 ms."""
    for i in range(50):
        store.add(
            f"Add step {i} to improve coverage",
            confidence=round(0.5 + i * 0.009, 3),
            parent_job_id="job-bulk",
        )
    start = time.perf_counter()
    all_s = store.list(parent_job_id="job-bulk")
    elapsed = (time.perf_counter() - start) * 1000
    assert len(all_s) == 50
    assert elapsed < 50, f"list(50 suggestions) took {elapsed:.1f} ms (limit 50 ms)"


def test_suggestions_apply_10_sequential_under_2s(store: SuggestionStore) -> None:
    """Applying 10 suggestions sequentially (no race conditions) takes under 2 s."""
    ids = [
        store.add(f"Fix issue {i}", confidence=0.8, parent_job_id="job-seq").id
        for i in range(10)
    ]
    start = time.perf_counter()
    for idx, sid in enumerate(ids):
        store.apply(sid, plan_id="plan-x", plan_version=idx + 1)
    elapsed = (time.perf_counter() - start) * 1000
    applied = store.list(applied=True, parent_job_id="job-seq")
    assert len(applied) == 10
    assert elapsed < 2000, f"apply(10 suggestions) took {elapsed:.1f} ms (limit 2000 ms)"


def test_suggestions_compare_large_sets_under_200ms(store: SuggestionStore) -> None:
    """Fetching two large suggestion sets and comparing them takes under 200 ms."""
    for i in range(100):
        store.add(f"Job A suggestion {i}", confidence=0.5, parent_job_id="job-a")
    for i in range(100):
        store.add(f"Job B suggestion {i}", confidence=0.6, parent_job_id="job-b")
    start = time.perf_counter()
    set_a = store.list(parent_job_id="job-a")
    set_b = store.list(parent_job_id="job-b")
    # Simulate diff: find suggestions in B with higher confidence than A average
    avg_a = sum(s.confidence for s in set_a) / len(set_a)
    better = [s for s in set_b if s.confidence > avg_a]
    elapsed = (time.perf_counter() - start) * 1000
    assert len(set_a) == 100
    assert len(set_b) == 100
    assert len(better) == 100  # all B have 0.6 > 0.5 average of A
    assert elapsed < 200, f"compare(100+100 suggestions) took {elapsed:.1f} ms (limit 200 ms)"
