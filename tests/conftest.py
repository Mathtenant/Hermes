"""Pytest fixtures & mocks."""

import hashlib
import math
import re
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hermes_assistant.llm.client import OllamaClient
from hermes_assistant.llm.tracing import JsonlTracer
from hermes_assistant.rag.store import ChromaStore

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def mock_post() -> Iterator[MagicMock]:
    """Patch requests.post in the client module."""
    with patch("hermes_assistant.llm.client.requests.post") as mock:
        yield mock


@pytest.fixture
def tracer(tmp_path: Path) -> JsonlTracer:
    """A JSONL tracer writing to an isolated temp file."""
    return JsonlTracer(tmp_path / "trace.jsonl")


@pytest.fixture
def client(tracer: JsonlTracer) -> OllamaClient:
    """An OllamaClient wired to an isolated tracer (no live service)."""
    return OllamaClient(host="http://localhost:11434", tracer=tracer)


def make_response(payload: dict) -> MagicMock:
    """Build a MagicMock mimicking a successful requests.Response."""
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


class FakeEmbedder:
    """Deterministic, offline stand-in for OllamaClient's embedding methods.

    Produces L2-normalised hashed term-frequency vectors: texts that share more
    words land closer in cosine space. Stable across processes (SHA-256 hashing,
    not Python's randomised ``hash``), so retrieval tests are reproducible. It
    duck-types the two methods ingest/retrieve need — ``embed`` and
    ``embed_batch`` — and records calls for assertions.
    """

    DIM = 256

    def __init__(self) -> None:
        self.embed_calls: list[str] = []
        self.batch_calls: list[int] = []

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.DIM
        for token in re.findall(r"\w+", text.lower()):
            idx = int(hashlib.sha256(token.encode()).hexdigest(), 16) % self.DIM
            vec[idx] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def embed(self, model: str, text: str) -> list[float]:
        self.embed_calls.append(text)
        return self._vector(text)

    def embed_batch(self, model: str, texts: list[str]) -> list[list[float]]:
        self.batch_calls.append(len(texts))
        return [self._vector(t) for t in texts]


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    """A deterministic offline embedder usable wherever OllamaClient is."""
    return FakeEmbedder()


@pytest.fixture
def store(tmp_path: Path) -> ChromaStore:
    """An isolated ChromaStore backed by a temp directory."""
    return ChromaStore(tmp_path / "vectorstore", "hermes_corpus")


@pytest.fixture
def sample_md() -> Path:
    """Path to the committed HERMES sample document."""
    return FIXTURES / "hermes_sample.md"
