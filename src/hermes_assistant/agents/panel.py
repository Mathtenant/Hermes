"""Diverse panel evaluation — multi-model majority vote for rubric review.

The panel executor runs each model in sequence (model-outer iteration) so only
one model occupies VRAM at a time on a 16 GB machine. After all criteria are
scored by a given model, ``keep_alive=0`` is sent to release VRAM before
loading the next one.

Design decisions:
* **Model-outer iteration** — iterate models in the outer loop, criteria in the
  inner loop. Each model scores all criteria before the next model is loaded.
  This avoids repeatedly swapping models for every criterion.
* **Weighted voting** — each panelist has a weight (default 1.0 or from a
  calibration-derived κ file). Weight sums are accumulated per result; ties
  break pessimistically (fail > partial > pass).
* **First-call drop** — if a panelist's very first criterion call fails, the
  panelist is dropped from the entire review to avoid asymmetric coverage.
* **Degradation fallback** — if surviving panelists fall below ``min_judges``
  after all criteria, the panel falls back to ``critic.review()``
  (single-judge self-consistency) and marks ``fallback="self_consistency"``
  in the trace.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel

from hermes_assistant.agents.critic import (
    CheckSample,
    SampleClient,
    aggregate,
    criterion_messages,
    verify_evidence,
)
from hermes_assistant.agents.critic import (
    review as _critic_review,
)
from hermes_assistant.config import settings
from hermes_assistant.hermes.model import Finding, ReviewResult, Severity
from hermes_assistant.library.model import FailureMode
from hermes_assistant.llm.client import OllamaError
from hermes_assistant.llm.roster import PANEL, ModelConfig, ModelMode
from hermes_assistant.rubrics.model import Criterion, Rubric

logger = logging.getLogger(__name__)

# Pessimistic tie-break order: fail beats partial beats pass.
_RESULT_ORDER: tuple[str, ...] = ("fail", "partial", "pass")

# Type alias for the three result strings.
_ResultStr = Literal["pass", "partial", "fail"]


# --------------------------------------------------------------------------- #
# Data models
# --------------------------------------------------------------------------- #

class PanelVote(BaseModel):
    """One panelist's vote on a single criterion."""

    model: str
    result: Literal["pass", "partial", "fail"]
    weight: float
    evidence_verified: bool
    sample: CheckSample


class PanelDecision(BaseModel):
    """Aggregated panel decision for one criterion."""

    criterion_id: str
    result: Literal["pass", "partial", "fail"]
    confidence: float
    votes: list[PanelVote]
    degraded: bool  # one or more panelists dropped/failed on this criterion
    unanimous: bool  # all active panelists agree


# --------------------------------------------------------------------------- #
# Voting
# --------------------------------------------------------------------------- #

def weighted_vote(votes: list[PanelVote]) -> tuple[str, float]:
    """Deterministic majority vote with weight-sum aggregation.

    Zero-weight votes are excluded from the denominator (they do not inflate
    total weight and thus do not dilute confidence).

    Tie-break is pessimistic: ``fail > partial > pass``.

    Args:
        votes: Non-empty list of panelist votes.

    Returns:
        ``(winning_result, confidence)`` where confidence =
        ``winner_weight_sum / total_active_weight_sum``.

    Raises:
        ValueError: If ``votes`` is empty.
    """
    if not votes:
        raise ValueError("weighted_vote requires at least one vote")

    weight_sums: dict[str, float] = {}
    total_weight = 0.0

    for v in votes:
        if v.weight > 0:
            weight_sums[v.result] = weight_sums.get(v.result, 0.0) + v.weight
            total_weight += v.weight

    if not weight_sums:
        # All votes have zero weight — fall back to unweighted count.
        for v in votes:
            weight_sums[v.result] = weight_sums.get(v.result, 0.0) + 1.0
        total_weight = float(len(votes))

    top_weight = max(weight_sums.values())
    # Pessimistic tie-break: first match in _RESULT_ORDER wins.
    winner = next(r for r in _RESULT_ORDER if weight_sums.get(r, 0.0) == top_weight)
    confidence = weight_sums[winner] / total_weight if total_weight > 0 else 0.0
    return winner, round(confidence, 6)


# --------------------------------------------------------------------------- #
# Panel resolution
# --------------------------------------------------------------------------- #

def resolve_panel(models: list[str] | None = None) -> list[ModelConfig]:
    """Resolve the panel model configurations.

    Resolution priority:
    1. If ``models`` is provided, build minimal ``ModelConfig`` for each ID.
    2. If ``settings.panel_models`` is a non-empty CSV string, parse it.
    3. Otherwise return the default ``PANEL`` roster.

    Args:
        models: Explicit list of model IDs, or ``None`` to use settings/roster.

    Returns:
        Ordered list of ``ModelConfig`` objects for panel execution.
    """
    if models is not None:
        return [
            ModelConfig(
                id=m,
                mode=ModelMode.INSTRUCT,
                description=f"Panel judge — {m}",
            )
            for m in models
        ]
    if settings.panel_models:
        model_ids = [m.strip() for m in settings.panel_models.split(",") if m.strip()]
        return [
            ModelConfig(
                id=m,
                mode=ModelMode.INSTRUCT,
                description=f"Panel judge — {m}",
            )
            for m in model_ids
        ]
    return list(PANEL)


# --------------------------------------------------------------------------- #
# Per-criterion panel execution
# --------------------------------------------------------------------------- #

def panel_check_criterion(
    deliverable_text: str,
    criterion: Criterion,
    rubric: Rubric,
    client: SampleClient,
    *,
    panelists: list[str],
    weights: dict[str, float] | None = None,
    samples: int = 1,
    num_ctx: int = 4096,
    failure_modes: list[FailureMode] | None = None,
) -> tuple[Finding, dict[str, Any]]:
    """Check one criterion with a diverse panel of models.

    Each panelist makes one ``structured()`` call via the client. Evidence is
    verified per vote. Votes are aggregated with ``weighted_vote()``, applying
    the hallucination guard (unverifiable non-pass is neutralised to pass).

    Args:
        deliverable_text: Full text of the deliverable being reviewed.
        criterion: The rubric criterion to evaluate.
        rubric: The full rubric (for system prompt context).
        client: A :class:`SampleClient`-compatible client.
        panelists: Ordered list of model IDs to use as judges.
        weights: Optional per-model weight override. Absent models get 1.0.
        samples: Self-consistency samples per panelist (default 1).
        num_ctx: Context window size for each call.
        failure_modes: Optional library failure modes to inject into the prompt.

    Returns:
        ``(Finding, trace_dict)`` — the aggregated finding and a trace dict
        with per-panelist vote details suitable for the per-job JSONL log.
    """
    messages = criterion_messages(
        deliverable_text, criterion, rubric, failure_modes=failure_modes
    )
    votes: list[PanelVote] = []
    panelist_results: dict[str, str] = {}

    for model_id in panelists:
        weight = (weights or {}).get(model_id, 1.0)
        try:
            sample = client.structured(
                model_id, messages, CheckSample,
                temperature=0.1, num_ctx=num_ctx,
            )
        except OllamaError as exc:
            logger.warning(
                "panel_check_criterion: panelist %s failed on %s: %s",
                model_id, criterion.id, exc,
            )
            continue

        ev = verify_evidence(sample.evidence_quote, deliverable_text)
        # Hallucination guard: neutralise a non-pass whose evidence cannot be
        # verified against the document.
        actual_result: _ResultStr = sample.result
        if actual_result != "pass" and criterion.evidence_required and not ev:
            actual_result = "pass"

        votes.append(
            PanelVote(
                model=model_id,
                result=actual_result,
                weight=weight,
                evidence_verified=ev,
                sample=sample,
            )
        )
        panelist_results[model_id] = actual_result

    if not votes:
        # No panelist produced output — record an honest non-finding.
        finding = Finding(
            criterion_id=criterion.id,
            dimension=criterion.dimension.value,
            result="pass",
            severity=None,
            location="",
            evidence_quote="",
            rationale="Panel unavailable — criterion not evaluated.",
            fix_suggestion="",
            confidence=0.0,
        )
        trace: dict[str, Any] = {
            "criterion_id": criterion.id,
            "panelists": [],
            "votes": {},
            "weights": {},
            "confidence": 0.0,
            "degraded": True,
            "unanimous": True,
            "fallback": None,
        }
        return finding, trace

    winning_result, confidence = weighted_vote(votes)
    winning_r: _ResultStr = winning_result  # type: ignore[assignment]

    # Representative vote from the winning side.
    rep_vote = next(v for v in votes if v.result == winning_result)
    severity: Severity | None = criterion.severity_if_failed if winning_result != "pass" else None
    unanimous = len({v.result for v in votes}) == 1

    finding = Finding(
        criterion_id=criterion.id,
        dimension=criterion.dimension.value,
        result=winning_r,
        severity=severity,
        location=rep_vote.sample.location,
        evidence_quote=rep_vote.sample.evidence_quote,
        rationale=rep_vote.sample.rationale,
        fix_suggestion=rep_vote.sample.fix_suggestion,
        confidence=round(confidence, 3),
    )

    eff_weights = {v.model: v.weight for v in votes}
    trace = {
        "criterion_id": criterion.id,
        "panelists": list(panelist_results.keys()),
        "votes": dict(panelist_results),
        "weights": eff_weights,
        "confidence": round(confidence, 3),
        "degraded": len(votes) < len(panelists),
        "unanimous": unanimous,
        "fallback": None,
    }
    return finding, trace


# --------------------------------------------------------------------------- #
# Full panel review
# --------------------------------------------------------------------------- #

def panel_review(
    deliverable_text: str,
    rubric: Rubric,
    client: SampleClient,
    *,
    panelists: list[str] | None = None,
    weights: dict[str, float] | None = None,
    samples: int = 1,
    min_judges: int = 2,
    num_ctx: int = 4096,
    on_criterion: Callable[[dict[str, Any]], None] | None = None,
    failure_modes: list[FailureMode] | None = None,
) -> ReviewResult:
    """Run a full rubric review with a diverse panel of models.

    Uses **model-outer iteration**: for each panelist, all criteria are scored
    before the next model is loaded into VRAM. ``keep_alive=0`` is sent on the
    last criterion call for each model to release VRAM before loading the next.

    Failure handling:
    * **First-call drop** — a panelist whose very first criterion call raises
      :class:`~hermes_assistant.llm.client.OllamaError` is dropped from the
      entire review (logged at WARNING level).
    * **Degradation fallback** — if surviving panelists are fewer than
      ``min_judges`` after all models have been processed, the review falls
      back to :func:`hermes_assistant.agents.critic.review` (single-judge
      self-consistency) and records ``fallback="self_consistency"`` in every
      on_criterion trace.

    Args:
        deliverable_text: Full text of the deliverable being reviewed.
        rubric: Rubric to execute.
        client: A :class:`SampleClient`-compatible client.
        panelists: Explicit model IDs. ``None`` → resolved via
            :func:`resolve_panel` (settings CSV or default PANEL roster).
        weights: Per-model vote weights. Absent models default to 1.0.
        samples: Self-consistency samples per panelist per criterion.
        min_judges: Minimum number of surviving panelists before fallback.
        num_ctx: Context window size passed to each model.
        on_criterion: Optional callback invoked after each criterion is
            aggregated; receives a trace dict describing the panel decision.
        failure_modes: Library failure modes to inject into criterion prompts.

    Returns:
        A :class:`~hermes_assistant.hermes.model.ReviewResult` (same schema as
        the single-judge path; trace details are in on_criterion callbacks).
    """
    panelist_configs = resolve_panel(panelists)
    active_models = [c.id for c in panelist_configs]

    # Pre-build criterion messages once (identical for all panelists).
    messages_by_criterion: dict[str, list[dict[str, str]]] = {
        c.id: criterion_messages(
            deliverable_text, c, rubric, failure_modes=failure_modes
        )
        for c in rubric.criteria
    }

    # per_model_results[model_id][criterion_id] = CheckSample or None
    per_model_results: dict[str, dict[str, CheckSample | None]] = {}
    dropped: set[str] = set()
    n_criteria = len(rubric.criteria)

    for model_id in active_models:
        per_model_results[model_id] = {}

        for i, criterion in enumerate(rubric.criteria):
            is_last = i == n_criteria - 1
            # Send keep_alive=0 on the last criterion to release VRAM after
            # this model finishes all its work.
            ka: int | str | None = 0 if is_last else None
            msgs = messages_by_criterion[criterion.id]

            try:
                sample = client.structured(
                    model_id, msgs, CheckSample,
                    temperature=0.1, num_ctx=num_ctx,
                    keep_alive=ka,
                )
                per_model_results[model_id][criterion.id] = sample
            except OllamaError as exc:
                logger.warning(
                    "panel panelist %s failed on criterion %s: %s",
                    model_id, criterion.id, exc,
                )
                if i == 0:
                    # First-call drop: omit this panelist from the entire review.
                    dropped.add(model_id)
                    logger.warning(
                        "Dropped panelist %s from review (first-call failure)", model_id
                    )
                    break
                else:
                    per_model_results[model_id][criterion.id] = None

    surviving = [m for m in active_models if m not in dropped]

    # ------------------------------------------------------------------ #
    # Degradation fallback
    # ------------------------------------------------------------------ #
    if len(surviving) < min_judges:
        logger.warning(
            "Panel has only %d surviving judge(s), below min_judges=%d; "
            "falling back to single-judge self-consistency review",
            len(surviving), min_judges,
        )
        result = _critic_review(
            deliverable_text, rubric, client,
            num_ctx=num_ctx, failure_modes=failure_modes,
        )
        if on_criterion is not None:
            for finding in result.findings:
                on_criterion(
                    {
                        "criterion_id": finding.criterion_id,
                        "panelists": surviving,
                        "votes": {},
                        "weights": {},
                        "confidence": finding.confidence,
                        "degraded": True,
                        "unanimous": False,
                        "fallback": "self_consistency",
                    }
                )
        return result

    # ------------------------------------------------------------------ #
    # Aggregate per-criterion across surviving panelists
    # ------------------------------------------------------------------ #
    findings: list[Finding] = []

    for criterion in rubric.criteria:
        votes: list[PanelVote] = []

        for model_id in surviving:
            maybe_sample: CheckSample | None = per_model_results[model_id].get(criterion.id)
            if maybe_sample is None:
                continue  # this panelist failed on this (non-first) criterion
            sample = maybe_sample

            weight = (weights or {}).get(model_id, 1.0)
            ev = verify_evidence(sample.evidence_quote, deliverable_text)

            # Hallucination guard: neutralise unverifiable non-pass evidence.
            actual_result: _ResultStr = sample.result
            if actual_result != "pass" and criterion.evidence_required and not ev:
                actual_result = "pass"

            votes.append(
                PanelVote(
                    model=model_id,
                    result=actual_result,
                    weight=weight,
                    evidence_verified=ev,
                    sample=sample,
                )
            )

        criterion_degraded = len(votes) < len(surviving)

        if not votes:
            finding = Finding(
                criterion_id=criterion.id,
                dimension=criterion.dimension.value,
                result="pass",
                severity=None,
                location="",
                evidence_quote="",
                rationale="Panel unavailable — criterion not evaluated.",
                fix_suggestion="",
                confidence=0.0,
            )
            final_confidence = 0.0
            unanimous = True
        else:
            winning_result, final_confidence = weighted_vote(votes)
            winning_r: _ResultStr = winning_result  # type: ignore[assignment]
            rep = next(v for v in votes if v.result == winning_result)
            sev: Severity | None = (
                criterion.severity_if_failed if winning_result != "pass" else None
            )
            finding = Finding(
                criterion_id=criterion.id,
                dimension=criterion.dimension.value,
                result=winning_r,
                severity=sev,
                location=rep.sample.location,
                evidence_quote=rep.sample.evidence_quote,
                rationale=rep.sample.rationale,
                fix_suggestion=rep.sample.fix_suggestion,
                confidence=round(final_confidence, 3),
            )
            unanimous = len({v.result for v in votes}) == 1

        findings.append(finding)

        if on_criterion is not None:
            on_criterion(
                {
                    "criterion_id": criterion.id,
                    "panelists": [v.model for v in votes],
                    "votes": {v.model: v.result for v in votes},
                    "weights": {v.model: v.weight for v in votes},
                    "confidence": round(final_confidence, 3),
                    "degraded": criterion_degraded,
                    "unanimous": unanimous,
                    "fallback": None,
                }
            )

    return aggregate(rubric, findings)
