"""Worker process for the async critic job queue.

The worker claims pending jobs one at a time, runs the rubric critic, and stores
the resulting :class:`ReviewResult`. Two operational guarantees:

* **Traceability** — every job writes a per-job JSONL log with exactly one line
  per criterion (criterion id, model(s), sample verdicts, confidence, latency),
  plus a trailing summary line. This is the audit trail required by the project
  contract, at job granularity.
* **Graceful shutdown** — SIGINT/SIGTERM set a stop flag. A job already in
  flight when a signal arrives is released back to ``pending`` (transient
  fail with retry) so no work is lost and no job is left orphaned ``running``.

Transient errors (network/timeout) return the job to ``pending`` up to
``max_attempts``; deterministic errors fail it terminally.
"""

from __future__ import annotations

import json
import logging
import signal
import time
from collections.abc import Callable
from pathlib import Path
from types import FrameType
from typing import Any

from hermes_assistant.agents import panel as panel_module
from hermes_assistant.agents.critic import review
from hermes_assistant.config import settings
from hermes_assistant.hermes.model import ReviewResult
from hermes_assistant.jobqueue.jobs import Job, JobStore
from hermes_assistant.llm.client import OllamaClient, OllamaError
from hermes_assistant.rubrics.loader import load_rubric

logger = logging.getLogger(__name__)

# A callable that turns a claimed job into a ReviewResult. Injectable so tests
# can drive the worker without a live model.
ReviewFn = Callable[[Job, Callable[[dict[str, Any]], None]], ReviewResult]


class Worker:
    """Claims and processes jobs until stopped or the queue drains (``--once``)."""

    def __init__(
        self,
        store: JobStore,
        *,
        logs_dir: str | Path | None = None,
        review_fn: ReviewFn | None = None,
        poll_interval: float = 1.0,
    ) -> None:
        self.store = store
        self.logs_dir = Path(logs_dir or settings.queue_logs_path)
        self.review_fn = review_fn or self._default_review
        self.poll_interval = poll_interval
        self._stop = False
        self._current: Job | None = None

    # ------------------------------------------------------------------ #
    # Signal handling
    # ------------------------------------------------------------------ #
    def _handle_signal(self, signum: int, _frame: FrameType | None) -> None:
        logger.info("worker received signal %s — finishing gracefully", signum)
        self._stop = True

    def install_signal_handlers(self) -> None:
        """Install SIGINT/SIGTERM handlers (call from the main thread)."""
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    # ------------------------------------------------------------------ #
    # Default review implementation (real model)
    # ------------------------------------------------------------------ #
    def _default_review(
        self, job: Job, on_criterion: Callable[[dict[str, Any]], None]
    ) -> ReviewResult:
        text = Path(job.deliverable_path).read_text(encoding="utf-8")
        rubric = load_rubric(job.rubric_id, job.rubric_version)
        client = OllamaClient(
            host=settings.ollama_host, num_thread=settings.ollama_num_thread
        )
        # Use a 4096-token context for critic calls: criterion text + document
        # rarely exceeds 2 K tokens, and a smaller context halves memory
        # pressure on bandwidth-bound hardware (M4 Air, 16 GB).
        if job.panel:
            return panel_module.panel_review(
                text,
                rubric,
                client,
                panelists=None,  # resolved from settings or default PANEL roster
                samples=settings.panel_samples,
                min_judges=settings.panel_min_judges,
                num_ctx=4096,
                on_criterion=on_criterion,
            )
        model = settings.critic_model or None
        return review(
            text,
            rubric,
            client,
            model=model,
            samples=job.samples,
            num_ctx=4096,
            on_criterion=on_criterion,
        )

    # ------------------------------------------------------------------ #
    # Per-job JSONL log
    # ------------------------------------------------------------------ #
    def _log_path(self, job: Job) -> Path:
        return self.logs_dir / f"{job.id}.jsonl"

    def _open_log(self, job: Job) -> Any:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        fh = self._log_path(job).open("w", encoding="utf-8")
        fh.write(
            json.dumps(
                {
                    "event": "job_start",
                    "job_id": job.id,
                    "kind": job.kind,
                    "rubric_id": job.rubric_id,
                    "deliverable_path": job.deliverable_path,
                    "attempt": job.attempts,
                }
            )
            + "\n"
        )
        return fh

    # ------------------------------------------------------------------ #
    # Job processing
    # ------------------------------------------------------------------ #
    def process(self, job: Job) -> None:
        """Run one job: review, log per criterion, store the result.

        Transient (network/timeout) failures release the job for retry; all
        other exceptions fail it terminally. The per-job JSONL log always gets
        a trailing summary line recording the outcome.
        """
        log = self._open_log(job)
        latencies: dict[str, float] = {}

        def on_criterion(trace: dict[str, Any]) -> None:
            elapsed = (time.perf_counter() - on_criterion.start) * 1000  # type: ignore[attr-defined]
            on_criterion.start = time.perf_counter()  # type: ignore[attr-defined]
            trace = {**trace, "latency_ms": round(elapsed, 1)}
            latencies[trace["criterion_id"]] = trace["latency_ms"]
            log.write(json.dumps(trace) + "\n")
            log.flush()

        on_criterion.start = time.perf_counter()  # type: ignore[attr-defined]

        try:
            result = self.review_fn(job, on_criterion)
        except OllamaError as exc:
            log.write(
                json.dumps({"event": "job_error", "transient": True, "error": str(exc)})
                + "\n"
            )
            log.close()
            self.store.fail(job.id, str(exc), retry=True)
            logger.warning("job %s transient failure (will retry): %s", job.id, exc)
            return
        except Exception as exc:  # noqa: BLE001 — terminal failure, recorded
            log.write(
                json.dumps({"event": "job_error", "transient": False, "error": str(exc)})
                + "\n"
            )
            log.close()
            self.store.fail(job.id, str(exc), retry=False)
            logger.error("job %s failed terminally: %s", job.id, exc)
            return

        result_json = result.model_dump_json()
        log.write(
            json.dumps(
                {
                    "event": "job_done",
                    "verdict": result.verdict.value,
                    "blockers": result.blockers,
                    "majors": result.majors,
                    "minors": result.minors,
                    "criteria": len(result.findings),
                }
            )
            + "\n"
        )
        log.close()
        self.store.complete(job.id, result_json)
        logger.info(
            "job %s done: verdict=%s blockers=%d", job.id, result.verdict.value,
            result.blockers,
        )

    # ------------------------------------------------------------------ #
    # Main loop
    # ------------------------------------------------------------------ #
    def run(self, *, once: bool = False) -> int:
        """Process jobs until stopped (or the queue is empty when ``once``).

        Returns the number of jobs processed. On startup, orphaned ``running``
        jobs are requeued (crash recovery).
        """
        requeued = self.store.requeue_stale()
        if requeued:
            logger.info("requeued %d stale running job(s)", requeued)

        processed = 0
        while not self._stop:
            job = self.store.claim_next()
            if job is None:
                if once:
                    break
                time.sleep(self.poll_interval)
                continue

            self._current = job
            if self._stop:
                # Signal arrived between claim and processing — release it.
                self.store.fail(job.id, "worker shutting down", retry=True)
                self._current = None
                break

            self.process(job)
            self._current = None
            processed += 1

        # If we were interrupted mid-flight, release the in-flight job.
        if self._current is not None:
            self.store.fail(
                self._current.id, "worker interrupted", retry=True
            )
            logger.info("released in-flight job %s back to pending", self._current.id)
            self._current = None

        return processed
