"""Pre-mortem agent — spec §15, §4.5, §18.

Generates failure scenarios for a :class:`~hermes_assistant.hermes.model.ProjectPlan`
by asking the critic model to imagine the project has already failed and enumerate
the most plausible root causes.  Each scenario is returned as a
:class:`~hermes_assistant.hermes.model.RiskItem`.

Design invariants
-----------------
* **Graceful degradation** — if every model is unavailable, returns an empty
  :class:`PreMortemPass` and logs a warning.  The caller is never blocked.
* **Traceability** — every model call (success or failure) appends a
  :class:`~hermes_assistant.llm.tracing.TraceRecord` to the configured JSONL log.
* **Offline fallback** — cascades CRITIC → CRITIC fallback → qwen3:4b.
* **No loops** — one structured call per model in the cascade; no refinement.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from pydantic import BaseModel

from hermes_assistant.hermes.model import ProjectPlan, RiskItem
from hermes_assistant.llm.client import OllamaError
from hermes_assistant.llm.roster import ModelRole, get_model_config
from hermes_assistant.llm.tracing import JsonlTracer, TraceRecord

logger = logging.getLogger(__name__)

_OFFLINE_FALLBACK_MODEL = "qwen3:4b"
_DEFAULT_NUM_CTX = 8192


# --------------------------------------------------------------------------- #
# Output model
# --------------------------------------------------------------------------- #
class PreMortemPass(BaseModel):
    """Structured output of a pre-mortem analysis pass.

    Used both as the public return type and as the ``schema`` argument passed
    to ``client.structured()`` — one flat, grammar-constrainable class.
    """

    risks: list[RiskItem]


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #
def _build_messages(
    plan: ProjectPlan,
    prompt_override: str | None,
) -> list[dict[str, str]]:
    """Build the chat-message list for the pre-mortem prompt.

    ``prompt_override`` replaces the user turn entirely (useful in tests and
    for custom prompts passed via the CLI ``--prompt`` flag).
    """
    phases_text = "\n".join(
        f"- {ph.id} ({ph.name}): "
        f"milestones=[{', '.join(ms.name for ms in ph.milestones)}]; "
        f"outcomes=[{', '.join(oc.name for oc in ph.outcomes)}]"
        for ph in plan.phases
    )
    assumptions_text = (
        "\n".join(f"- {a}" for a in plan.open_assumptions) or "None stated."
    )
    risks_text = (
        "\n".join(f"- {r}" for r in plan.risks) or "None stated."
    )

    system = (
        "You are a senior HERMES 2022 risk analyst performing a pre-mortem. "
        "Assume the project has already failed. Identify the 3-5 most plausible "
        "failure scenarios. For each, produce a RiskItem with: description, impact, "
        "likelihood (Low / Medium / High), mitigation, residual_risk, and owner. "
        "Return ONLY valid JSON."
    )
    user = prompt_override or (
        f"PROJECT: {plan.title}\n"
        f"SCENARIO: {plan.scenario}\n\n"
        f"PHASES:\n{phases_text}\n\n"
        f"OPEN ASSUMPTIONS:\n{assumptions_text}\n\n"
        f"KNOWN RISKS:\n{risks_text}\n\n"
        "Enumerate the most likely failure scenarios as RiskItems (JSON)."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# --------------------------------------------------------------------------- #
# Public entrypoint
# --------------------------------------------------------------------------- #
def run_premortem(
    plan: ProjectPlan,
    prompt_override: str | None = None,
    *,
    client: Any = None,
    tracer: JsonlTracer | None = None,
    num_ctx: int = _DEFAULT_NUM_CTX,
) -> PreMortemPass:
    """Run a pre-mortem pass over ``plan`` and return structured failure scenarios.

    Parameters
    ----------
    plan:
        The project plan to analyse.
    prompt_override:
        If given, replaces the default user prompt verbatim.
    client:
        An object with a ``structured()`` method compatible with
        :class:`~hermes_assistant.llm.client.OllamaClient`.  If *None*, a new
        ``OllamaClient`` is constructed from ``settings``.
    tracer:
        JSONL tracer to record model calls.  If *None* and ``client`` is also
        *None*, the configured ``traces_path`` is used.  If *None* and
        ``client`` is injected (e.g. in tests), a no-op tracer is used.
    num_ctx:
        Token context window forwarded to the model.

    Returns
    -------
    PreMortemPass
        A (possibly empty) list of :class:`~hermes_assistant.hermes.model.RiskItem`
        objects.  Empty means all models were unavailable.
    """
    # ------------------------------------------------------------------ #
    # Build client / tracer
    # ------------------------------------------------------------------ #
    if client is None:
        from hermes_assistant.config import settings  # noqa: PLC0415
        from hermes_assistant.llm.client import OllamaClient  # noqa: PLC0415

        _tracer = tracer or JsonlTracer(settings.traces_path)
        client = OllamaClient(host=settings.ollama_host, tracer=_tracer)
        tracer = _tracer
    elif tracer is None:
        tracer = JsonlTracer(None)  # no-op; injected client may have its own

    # ------------------------------------------------------------------ #
    # Build model cascade
    # ------------------------------------------------------------------ #
    cfg = get_model_config(ModelRole.CRITIC)
    models_to_try: list[str] = [cfg.id]
    if cfg.fallback and cfg.fallback != cfg.id:
        models_to_try.append(cfg.fallback)
    if _OFFLINE_FALLBACK_MODEL not in models_to_try:
        models_to_try.append(_OFFLINE_FALLBACK_MODEL)

    messages = _build_messages(plan, prompt_override)
    prompt_hash = hashlib.sha256(
        json.dumps(messages, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]

    # ------------------------------------------------------------------ #
    # Try each model in cascade
    # ------------------------------------------------------------------ #
    for model_id in models_to_try:
        t0 = time.monotonic()
        try:
            response: PreMortemPass = client.structured(
                model_id,
                messages,
                PreMortemPass,
                temperature=0.3,
                num_ctx=num_ctx,
            )
            latency_ms = (time.monotonic() - t0) * 1000.0
            tracer.record(
                TraceRecord(
                    call_type="structured",
                    model=model_id,
                    mode="instruct",
                    prompt_hash=prompt_hash,
                    latency_ms=latency_ms,
                    success=True,
                    extra={"agent": "premortem", "plan_title": plan.title},
                )
            )
            logger.info(
                "premortem: model=%s risks=%d", model_id, len(response.risks)
            )
            return response
        except OllamaError as exc:
            latency_ms = (time.monotonic() - t0) * 1000.0
            logger.warning("premortem: model %s failed: %s", model_id, exc)
            tracer.record(
                TraceRecord(
                    call_type="structured",
                    model=model_id,
                    mode="instruct",
                    prompt_hash=prompt_hash,
                    latency_ms=latency_ms,
                    success=False,
                    error=str(exc),
                    extra={"agent": "premortem"},
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "premortem: unexpected error on %s: %s", model_id, exc
            )
            break

    logger.warning("premortem: all models unavailable — returning empty result")
    return PreMortemPass(risks=[])
