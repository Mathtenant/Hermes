"""Ollama client wrapper with structured output, retry & traceability.

All inference is local: the client refuses any non-loopback host. Every call
(chat / structured / embed / health) emits a :class:`TraceRecord` to the
configured :class:`JsonlTracer`.

Options note — ``num_gpu``:
    When passed in the Ollama options dict, ``num_gpu`` controls GPU layer
    offloading: 0 = CPU-only, 1+ = GPU layers. Per spec §11, ROUTER and EMBED
    run fully on GPU (num_gpu=1); 30B models share CPU/GPU as needed.
    The ``chat()`` and ``structured()`` methods accept ``num_gpu`` and forward
    it transparently to the Ollama options payload.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, TypeVar
from urllib.parse import urlparse

import requests
from pydantic import BaseModel, ValidationError

from hermes_assistant.config import settings
from hermes_assistant.llm.tracing import JsonlTracer, TraceRecord, hash_prompt

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

# Only loopback hosts are permitted — no confidential data may leave the box.
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


# --------------------------------------------------------------------------- #
# Error hierarchy
# --------------------------------------------------------------------------- #
class OllamaError(Exception):
    """Base class for all Ollama client errors."""


class OllamaConnectionError(OllamaError):
    """Could not reach the local Ollama service."""


class OllamaTimeoutError(OllamaError):
    """Ollama did not respond within the timeout budget."""


class OllamaResponseError(OllamaError):
    """Ollama returned a non-2xx HTTP status."""


class OllamaValidationError(OllamaError):
    """Structured output failed schema validation after all retries."""

    def __init__(self, message: str, *, last_raw: str | None = None) -> None:
        super().__init__(message)
        self.last_raw = last_raw


# --------------------------------------------------------------------------- #
# Schema flattening
# --------------------------------------------------------------------------- #
def _flatten_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline ``$defs``/``$ref`` into a single self-contained JSON schema.

    Ollama's ``format`` grammar engine is happier with refs resolved inline.
    Nested Pydantic models (e.g. ``ReviewResult`` holding ``list[Finding]``)
    and enum ``$defs`` are expanded in place. Non-recursive schemas only.
    """
    defs: dict[str, Any] = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = str(node["$ref"]).split("/")[-1]
                resolved = resolve(dict(defs.get(name, {})))
                for key, value in node.items():
                    if key != "$ref":
                        resolved[key] = resolve(value)
                return resolved
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    flat = {k: resolve(v) for k, v in schema.items() if k != "$defs"}
    return flat


class OllamaClient:
    """Wrapper around the Ollama HTTP API with schema validation & retry."""

    def __init__(
        self,
        host: str = "http://localhost:11434",
        num_thread: int = 10,
        *,
        tracer: JsonlTracer | None = None,
    ) -> None:
        """Initialize the Ollama client.

        Args:
            host: Ollama service URL. MUST be a loopback host.
            num_thread: Physical cores for inference (not hyperthreads).
            tracer: Trace sink. Defaults to the configured JSONL trace file.

        Raises:
            ValueError: If ``host`` is not a loopback address.
        """
        hostname = urlparse(host).hostname
        if hostname not in _LOOPBACK_HOSTS:
            raise ValueError(
                f"Refusing non-local Ollama host {host!r}: only loopback "
                f"({', '.join(sorted(_LOOPBACK_HOSTS))}) is permitted."
            )
        self.host = host.rstrip("/")
        self.num_thread = num_thread
        self.tracer = tracer if tracer is not None else JsonlTracer(settings.traces_path)

    # ----------------------------------------------------------------- #
    # Transport
    # ----------------------------------------------------------------- #
    def _post(self, path: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
        """POST JSON to Ollama, translating transport errors into OllamaError."""
        url = f"{self.host}{path}"
        try:
            response = requests.post(url, json=payload, timeout=timeout)
            response.raise_for_status()
        except requests.exceptions.ConnectTimeout as exc:
            raise OllamaTimeoutError(f"Timed out connecting to {url}") from exc
        except requests.exceptions.ReadTimeout as exc:
            raise OllamaTimeoutError(f"Timed out reading from {url}") from exc
        except requests.exceptions.Timeout as exc:
            raise OllamaTimeoutError(f"Request to {url} timed out") from exc
        except requests.exceptions.ConnectionError as exc:
            raise OllamaConnectionError(f"Cannot reach Ollama at {url}") from exc
        except requests.exceptions.HTTPError as exc:
            raise OllamaResponseError(f"Ollama returned an error for {url}: {exc}") from exc
        data: dict[str, Any] = response.json()
        return data

    def _trace(
        self,
        *,
        call_type: str,
        model: str,
        mode: str,
        prompt_hash: str,
        latency_ms: float,
        data: dict[str, Any] | None = None,
        success: bool = True,
        error: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        prompt_tokens = data.get("prompt_eval_count") if data else None
        completion_tokens = data.get("eval_count") if data else None
        total: int | None
        if prompt_tokens is not None or completion_tokens is not None:
            total = (prompt_tokens or 0) + (completion_tokens or 0)
        else:
            total = None
        self.tracer.record(
            TraceRecord(
                call_type=call_type,
                model=model,
                mode=mode,
                prompt_hash=prompt_hash,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total,
                success=success,
                error=error,
                extra=extra or {},
            )
        )

    # ----------------------------------------------------------------- #
    # Public API
    # ----------------------------------------------------------------- #
    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        think: bool | None = None,
        num_ctx: int = 8192,
        temperature: float = 0.2,
        keep_alive: int | str | None = None,
        num_gpu: int | None = None,
    ) -> str:
        """Plain chat completion.

        Args:
            model: Model ID (e.g. 'qwen3:4b').
            messages: List of {role, content} dicts.
            think: Enable reasoning mode on capable models (top-level param).
            num_ctx: Context window size.
            temperature: Sampling temperature.
            keep_alive: Ollama keep-alive duration (e.g. ``0`` to unload
                immediately, ``"5m"`` for 5 minutes). ``None`` uses Ollama's
                default. Useful in the panel executor to release each model
                from VRAM before loading the next one.
            num_gpu: GPU layers to offload (0=CPU-only, 1+=GPU). ``None``
                uses Ollama's default. Per spec §11, set to 1 for ROUTER/EMBED.

        Returns:
            Generated text response.
        """
        options: dict[str, Any] = {
            "num_ctx": num_ctx,
            "temperature": temperature,
            "num_thread": self.num_thread,
        }
        if num_gpu is not None:
            options["num_gpu"] = num_gpu
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": options,
        }
        # `think` is a TOP-LEVEL field in the Ollama chat API, not an option.
        if think is not None:
            payload["think"] = think
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive

        prompt_hash = hash_prompt(messages)
        mode = "thinking" if think else "instruct"
        start = time.perf_counter()
        try:
            data = self._post("/api/chat", payload, timeout=300)
        except OllamaError as exc:
            self._trace(
                call_type="chat",
                model=model,
                mode=mode,
                prompt_hash=prompt_hash,
                latency_ms=(time.perf_counter() - start) * 1000,
                success=False,
                error=str(exc),
            )
            raise
        latency_ms = (time.perf_counter() - start) * 1000
        self._trace(
            call_type="chat",
            model=model,
            mode=mode,
            prompt_hash=prompt_hash,
            latency_ms=latency_ms,
            data=data,
        )
        content: str = data["message"]["content"]
        return content

    def structured(
        self,
        model: str,
        messages: list[dict[str, str]],
        schema: type[T],
        *,
        num_ctx: int = 8192,
        max_retries: int = 1,
        temperature: float = 0.1,
        keep_alive: int | str | None = None,
        num_gpu: int | None = None,
    ) -> T:
        """Grammar-constrained JSON -> validated Pydantic model.

        Retries (bounded) on JSON/validation failure, feeding the error back
        into the prompt. Each model attempt is traced individually.

        Args:
            model: Model ID.
            messages: Chat messages.
            schema: Pydantic model class to validate against.
            num_ctx: Context window.
            max_retries: Max retry attempts after the first call.
            temperature: Sampling temperature. Defaults to 0.1 (deterministic);
                the critic raises it on later self-consistency samples for
                diversity.
            keep_alive: Ollama keep-alive duration. ``None`` uses Ollama's
                default. Pass ``0`` to release the model from VRAM immediately
                after the call (used by panel executor on last criterion).
            num_gpu: GPU layers to offload (0=CPU-only, 1+=GPU). ``None``
                uses Ollama's default. Per spec §11, set to 1 for ROUTER/EMBED.

        Returns:
            Validated Pydantic model instance.

        Raises:
            OllamaValidationError: After retries exhausted.
            OllamaError: On transport/HTTP errors.
        """
        json_schema = _flatten_schema(schema.model_json_schema())
        attempt_messages = list(messages)
        last_raw: str | None = None

        for attempt in range(max_retries + 1):
            _options: dict[str, Any] = {
                "num_ctx": num_ctx,
                "temperature": temperature,
                "num_thread": self.num_thread,
            }
            if num_gpu is not None:
                _options["num_gpu"] = num_gpu
            payload: dict[str, Any] = {
                "model": model,
                "messages": attempt_messages,
                "stream": False,
                "format": json_schema,
                "options": _options,
            }
            if keep_alive is not None:
                payload["keep_alive"] = keep_alive
            prompt_hash = hash_prompt(attempt_messages)
            start = time.perf_counter()
            try:
                data = self._post("/api/chat", payload, timeout=300)
            except OllamaError as exc:
                self._trace(
                    call_type="structured",
                    model=model,
                    mode="instruct",
                    prompt_hash=prompt_hash,
                    latency_ms=(time.perf_counter() - start) * 1000,
                    success=False,
                    error=str(exc),
                    extra={"attempt": attempt},
                )
                raise
            latency_ms = (time.perf_counter() - start) * 1000
            raw_text = data["message"]["content"]
            last_raw = raw_text

            try:
                parsed = json.loads(raw_text)
                validated = schema.model_validate(parsed)
            except (json.JSONDecodeError, ValidationError) as exc:
                self._trace(
                    call_type="structured",
                    model=model,
                    mode="instruct",
                    prompt_hash=prompt_hash,
                    latency_ms=latency_ms,
                    data=data,
                    success=False,
                    error=str(exc),
                    extra={"attempt": attempt, "validation_ok": False},
                )
                if attempt < max_retries:
                    logger.warning(
                        "structured attempt %d failed validation: %s. Retrying.",
                        attempt + 1,
                        exc,
                    )
                    attempt_messages = attempt_messages + [
                        {"role": "assistant", "content": raw_text},
                        {
                            "role": "user",
                            "content": (
                                f"Validation error: {exc}\n\n"
                                "Return ONLY valid JSON matching the schema."
                            ),
                        },
                    ]
                    continue
                raise OllamaValidationError(
                    f"Structured output failed validation after "
                    f"{max_retries + 1} attempts: {exc}",
                    last_raw=last_raw,
                ) from exc

            self._trace(
                call_type="structured",
                model=model,
                mode="instruct",
                prompt_hash=prompt_hash,
                latency_ms=latency_ms,
                data=data,
                extra={"attempt": attempt, "validation_ok": True},
            )
            return validated

        # Unreachable: loop either returns or raises.
        raise OllamaValidationError(  # pragma: no cover
            "Structured output exhausted retries", last_raw=last_raw
        )

    def embed(self, model: str, text: str) -> list[float]:
        """Generate embeddings.

        Args:
            model: Embedding model ID (e.g. 'bge-m3').
            text: Text to embed.

        Returns:
            Embedding vector.
        """
        payload = {"model": model, "input": text}
        prompt_hash = hash_prompt(text)
        start = time.perf_counter()
        try:
            data = self._post("/api/embed", payload, timeout=60)
        except OllamaError as exc:
            self._trace(
                call_type="embed",
                model=model,
                mode="embed",
                prompt_hash=prompt_hash,
                latency_ms=(time.perf_counter() - start) * 1000,
                success=False,
                error=str(exc),
            )
            raise
        latency_ms = (time.perf_counter() - start) * 1000
        self._trace(
            call_type="embed",
            model=model,
            mode="embed",
            prompt_hash=prompt_hash,
            latency_ms=latency_ms,
            data=data,
        )
        vector: list[float] = data["embeddings"][0]
        return vector

    def embed_batch(self, model: str, texts: list[str]) -> list[list[float]]:
        """Embed many texts in a single Ollama call.

        The Ollama ``/api/embed`` endpoint accepts a list ``input`` and returns
        one vector per item, in order. Batching amortises HTTP + model warm-up
        cost across the batch during ingest. One trace record is emitted per
        batch (``call_type="embed"``, ``extra.batch_size``), so every embedded
        chunk remains auditable.

        Args:
            model: Embedding model ID (e.g. 'bge-m3').
            texts: Texts to embed. An empty list returns an empty list without
                touching the network.

        Returns:
            One embedding vector per input text, in input order.
        """
        if not texts:
            return []
        payload = {"model": model, "input": texts}
        prompt_hash = hash_prompt(json.dumps(texts, sort_keys=True, ensure_ascii=False))
        start = time.perf_counter()
        try:
            data = self._post("/api/embed", payload, timeout=120)
        except OllamaError as exc:
            self._trace(
                call_type="embed",
                model=model,
                mode="embed",
                prompt_hash=prompt_hash,
                latency_ms=(time.perf_counter() - start) * 1000,
                success=False,
                error=str(exc),
                extra={"batch_size": len(texts)},
            )
            raise
        latency_ms = (time.perf_counter() - start) * 1000
        self._trace(
            call_type="embed",
            model=model,
            mode="embed",
            prompt_hash=prompt_hash,
            latency_ms=latency_ms,
            data=data,
            extra={"batch_size": len(texts)},
        )
        vectors: list[list[float]] = data["embeddings"]
        return vectors

    def health(self) -> dict[str, Any]:
        """Check whether the local Ollama service is reachable.

        Never raises: returns a status dict so callers can degrade gracefully.
        """
        url = f"{self.host}/api/tags"
        start = time.perf_counter()
        try:
            response = requests.get(url, timeout=2)
            response.raise_for_status()
            payload = response.json()
            models = [m.get("name") for m in payload.get("models", [])]
            status: dict[str, Any] = {
                "available": True,
                "host": self.host,
                "models": models,
                "error": None,
            }
        except (requests.RequestException, ValueError) as exc:
            status = {
                "available": False,
                "host": self.host,
                "models": [],
                "error": str(exc),
            }
        latency_ms = (time.perf_counter() - start) * 1000
        self._trace(
            call_type="health",
            model="",
            mode="",
            prompt_hash="",
            latency_ms=latency_ms,
            success=status["available"],
            error=status["error"],
        )
        return status
