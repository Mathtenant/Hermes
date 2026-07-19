"""Rubric critic — the *executor* of the compiler-executor pattern.

The rubric is a program; this module executes it criterion-by-criterion. For
each :class:`~hermes_assistant.rubrics.model.Criterion` the critic makes one
grammar-constrained ``structured()`` call (respecting the field budget of small
local models), optionally repeated ``samples`` times for self-consistency.

Design invariants (spec §4D / §4I):

* **CoT-before-score** — :class:`CheckSample` orders fields
  ``location -> evidence_quote -> rationale -> result`` so the model reasons and
  cites *before* it decides.
* **Evidence verification** — a failing/partial finding must quote text that is
  a verbatim (whitespace-normalised) substring of the document. Unverifiable
  evidence is treated as a hallucination and the criterion is neutralised.
* **Self-consistency** — N samples (sample 1 at temperature 0.1, 2..N at 0.7)
  are majority-voted; ties resolve pessimistically (fail > partial > pass);
  confidence is the winning share.
* **One pass, no loops** — aggregation is pure Python; no refinement loop, and
  the verdict never auto-approves (human sign-off remains required).
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Callable
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from hermes_assistant.hermes.model import (
    Finding,
    ReviewResult,
    Severity,
    Verdict,
)
from hermes_assistant.library.model import FailureMode
from hermes_assistant.llm.client import OllamaError
from hermes_assistant.llm.roster import ModelRole, get_model_config
from hermes_assistant.rubrics.model import Criterion, Rubric

logger = logging.getLogger(__name__)

# Results ordered from most to least severe — used for pessimistic tie-breaks
# and for picking the "worst" result per dimension.
_RESULT_ORDER: tuple[str, ...] = ("fail", "partial", "pass")

# Low-temperature first sample (deterministic), diverse thereafter.
_BASE_TEMPERATURE = 0.1
_DIVERSITY_TEMPERATURE = 0.7


class CheckSample(BaseModel):
    """One model judgement of a single criterion.

    Field order encodes chain-of-thought: the model must fix a ``location`` and
    quote ``evidence_quote`` and give a ``rationale`` *before* committing to a
    ``result``. ``severity``/``fix_suggestion`` follow. Flat & non-recursive so
    the client's schema flattener can grammar-constrain it.
    """

    location: str
    evidence_quote: str
    rationale: str
    result: Literal["pass", "partial", "fail"]
    severity: Severity
    fix_suggestion: str


class SampleClient(Protocol):
    """Structural type for the per-criterion call (duck-typed in tests)."""

    def structured(
        self,
        model: str,
        messages: list[dict[str, str]],
        schema: type[CheckSample],
        *,
        temperature: float = ...,
        num_ctx: int = ...,
        keep_alive: int | str | None = ...,
    ) -> CheckSample: ...


# --------------------------------------------------------------------------- #
# Model resolution (bias mitigation)
# --------------------------------------------------------------------------- #
def resolve_critic_models(model: str | None = None) -> tuple[str, str | None]:
    """Return ``(primary, fallback)`` critic model ids.

    Defaults to the roster CRITIC entry (a thinking-MoE, a *different family*
    from the instruct-MoE planner — judge ≠ draft, reducing self-preference
    bias) with its declared fallback (gpt-oss-20b). Never degrades to the
    planner model.
    """
    cfg = get_model_config(ModelRole.CRITIC)
    primary = model or cfg.id
    fallback = cfg.fallback if cfg.fallback != primary else None
    return primary, fallback


# --------------------------------------------------------------------------- #
# Evidence verification (hallucination guard)
# --------------------------------------------------------------------------- #
def _normalise_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def verify_evidence(quote: str, doc: str) -> bool:
    """Return True iff ``quote`` is a verbatim substring of ``doc``.

    Whitespace is normalised on both sides (collapsed runs, trimmed) so that
    reflowed line breaks do not cause false negatives. An empty quote never
    verifies — a finding must point at real text.
    """
    needle = _normalise_ws(quote)
    if not needle:
        return False
    return needle in _normalise_ws(doc)


# --------------------------------------------------------------------------- #
# Self-consistency voting
# --------------------------------------------------------------------------- #
def vote(samples: list[CheckSample]) -> tuple[str, float]:
    """Majority-vote the result; ties resolve pessimistically.

    Returns ``(result, confidence)`` where confidence is the winning result's
    share of all samples (the self-consistency agreement). With no samples the
    result is ``"pass"`` at zero confidence (nothing observed).
    """
    if not samples:
        return "pass", 0.0
    counts: dict[str, int] = Counter(str(s.result) for s in samples)
    top = max(counts.values())
    # Pessimistic tie-break: prefer fail, then partial, then pass.
    winner = next(r for r in _RESULT_ORDER if counts.get(r, 0) == top)
    return winner, counts[winner] / len(samples)


# --------------------------------------------------------------------------- #
# Per-criterion execution
# --------------------------------------------------------------------------- #
def criterion_messages(
    deliverable_text: str,
    criterion: Criterion,
    rubric: Rubric,
    *,
    failure_modes: list[FailureMode] | None = None,
) -> list[dict[str, str]]:
    anti = "\n".join(
        f"- {ap.id}: {ap.text.strip()} (FAIL e.g. {ap.example_fail!r}; "
        f"PASS e.g. {ap.example_pass!r})"
        for ap in rubric.anti_patterns
    )
    fm_section = ""
    if failure_modes:
        fm_lines = "\n".join(
            f"- [{fm.id}] {fm.title}: {fm.description}"
            + (f" Mitigation: {fm.mitigations[0]}" if fm.mitigations else "")
            for fm in failure_modes
        )
        fm_section = f"\n\nKnown failure modes from the library:\n{fm_lines}"
    system = (
        "You are a meticulous HERMES 2022 quality reviewer. You evaluate ONE "
        "rubric criterion against a deliverable and nothing else.\n"
        "Reason in this exact order and fill the fields in this order:\n"
        "1. location — where in the document you looked;\n"
        "2. evidence_quote — an EXACT, VERBATIM substring copied from the "
        "document that supports your judgement (copy characters exactly; do "
        "not paraphrase). If the criterion fails because something is MISSING, "
        "quote the nearest heading or line that should have contained it;\n"
        "3. rationale — why the evidence does or does not satisfy the "
        "criterion;\n"
        "4. result — pass, partial, or fail (only AFTER the above);\n"
        "5. severity and fix_suggestion.\n"
        "Judge strictly and length-neutrally: a longer answer is not a better "
        "one. Return ONLY valid JSON.\n\n"
        f"Known anti-patterns for this deliverable type:\n{anti}"
        f"{fm_section}"
    )
    user = (
        f"CRITERION [{criterion.id}] (dimension: {criterion.dimension.value}, "
        f"check: {criterion.check_type}):\n{criterion.text.strip()}\n\n"
        f"DOCUMENT:\n{deliverable_text}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# Backward-compat alias — existing internal call sites still work.
_criterion_messages = criterion_messages


def _one_sample(
    client: SampleClient,
    primary: str,
    fallback: str | None,
    messages: list[dict[str, str]],
    temperature: float,
    num_ctx: int = 8192,
) -> tuple[CheckSample | None, str | None]:
    """Run a single sample, transparently falling back on model failure.

    Returns ``(sample, model_used)`` or ``(None, None)`` if both models failed.
    A failure of the primary model is a bias-neutral event — the fallback is a
    *different family*, never the planner.
    """
    for model in (primary, fallback):
        if model is None:
            continue
        try:
            sample = client.structured(
                model, messages, CheckSample,
                temperature=temperature, num_ctx=num_ctx,
            )
            return sample, model
        except OllamaError as exc:
            logger.warning("critic sample on %s failed: %s", model, exc)
            continue
    return None, None


def _representative(
    samples: list[CheckSample], result: str, doc: str, *, need_evidence: bool
) -> tuple[CheckSample | None, bool]:
    """Pick a sample matching ``result``; prefer one with verified evidence.

    Returns ``(sample, evidence_verified)``. When evidence is required, a sample
    whose quote verifies is preferred; if none verifies, the first matching
    sample is returned with ``evidence_verified=False`` so the caller can apply
    the hallucination guard.
    """
    matching = [s for s in samples if s.result == result]
    if not matching:
        return None, False
    if need_evidence:
        for sample in matching:
            if verify_evidence(sample.evidence_quote, doc):
                return sample, True
        return matching[0], False
    # Evidence not required: still report verification status honestly.
    first = matching[0]
    return first, verify_evidence(first.evidence_quote, doc)


def check_criterion(
    deliverable_text: str,
    criterion: Criterion,
    rubric: Rubric,
    client: SampleClient,
    *,
    primary_model: str,
    fallback_model: str | None = None,
    samples: int = 3,
    num_ctx: int = 8192,
    failure_modes: list[FailureMode] | None = None,
) -> tuple[Finding, dict[str, Any]]:
    """Execute one criterion with self-consistency and evidence verification.

    Returns the :class:`Finding` plus a trace dict (for the per-job JSONL log)
    carrying the per-sample verdicts, the model(s) used, confidence and whether
    the evidence verified.
    """
    messages = criterion_messages(
        deliverable_text, criterion, rubric, failure_modes=failure_modes
    )
    collected: list[CheckSample] = []
    models_used: list[str] = []
    for i in range(max(1, samples)):
        temperature = _BASE_TEMPERATURE if i == 0 else _DIVERSITY_TEMPERATURE
        sample, model = _one_sample(
            client, primary_model, fallback_model, messages, temperature,
            num_ctx=num_ctx,
        )
        if sample is not None and model is not None:
            collected.append(sample)
            models_used.append(model)

    result, confidence = vote(collected)
    evidence_verified = False
    rep: CheckSample | None = None
    guard_triggered = False

    if not collected:
        # No model output at all — record an honest non-finding.
        finding = Finding(
            criterion_id=criterion.id,
            dimension=criterion.dimension.value,
            result="pass",
            severity=None,
            location="",
            evidence_quote="",
            rationale="Model unavailable — criterion not evaluated.",
            fix_suggestion="",
            confidence=0.0,
        )
    else:
        rep, evidence_verified = _representative(
            collected, result, deliverable_text,
            need_evidence=criterion.evidence_required,
        )
        # Hallucination guard: a fail/partial that requires evidence but whose
        # quote cannot be verified is neutralised to pass (never count a
        # fabricated defect as a blocker).
        if (
            result != "pass"
            and criterion.evidence_required
            and not evidence_verified
        ):
            guard_triggered = True
            severity: Severity | None = None
            location = rep.location if rep else ""
            evidence = rep.evidence_quote if rep else ""
            rationale = (
                "Evidence could not be verified against the document "
                "(possible hallucination); criterion treated as pass. "
                f"Model rationale was: {rep.rationale if rep else ''}"
            )
            fix = ""
            final_result: str = "pass"
            confidence = min(confidence, 0.34)
        else:
            final_result = result
            severity = (
                criterion.severity_if_failed if result != "pass" else None
            )
            location = rep.location if rep else ""
            evidence = rep.evidence_quote if rep else ""
            rationale = rep.rationale if rep else ""
            fix = rep.fix_suggestion if rep else ""

        finding = Finding(
            criterion_id=criterion.id,
            dimension=criterion.dimension.value,
            result=final_result,  # type: ignore[arg-type]
            severity=severity,
            location=location,
            evidence_quote=evidence,
            rationale=rationale,
            fix_suggestion=fix,
            confidence=round(confidence, 3),
        )

    trace = {
        "criterion_id": criterion.id,
        "dimension": criterion.dimension.value,
        "models": models_used,
        "sample_results": [s.result for s in collected],
        "confidence": round(confidence, 3),
        "result": finding.result,
        "severity": finding.severity.value if finding.severity else None,
        "evidence_verified": evidence_verified,
        "hallucination_guard": guard_triggered,
    }
    return finding, trace


# --------------------------------------------------------------------------- #
# Deterministic aggregation (pure Python — no LLM)
# --------------------------------------------------------------------------- #
def aggregate(rubric: Rubric, findings: list[Finding]) -> ReviewResult:
    """Fold per-criterion findings into a :class:`ReviewResult`.

    Severity counts consider only non-pass findings. Verdict is conservative:
    any blocker or major failure fails the review; only-minor issues pass with
    comments; a clean sweep passes. The verdict is a *review* judgement — it
    never constitutes sign-off (which requires a human).
    """
    non_pass = [f for f in findings if f.result != "pass"]
    blockers = sum(1 for f in non_pass if f.severity == Severity.blocker)
    majors = sum(1 for f in non_pass if f.severity == Severity.major)
    minors = sum(1 for f in non_pass if f.severity == Severity.minor)

    if blockers:
        verdict = Verdict.fail
        why = f"{blockers} blocker(s) must be resolved before sign-off."
    elif majors:
        verdict = Verdict.fail
        why = f"{majors} major issue(s) require rework before sign-off."
    elif minors:
        verdict = Verdict.pass_with_comments
        why = f"{minors} minor issue(s); acceptable with comments."
    else:
        verdict = Verdict.pass_
        why = "All criteria satisfied. Human sign-off still required."

    # Worst observed result per dimension (fail > partial > pass).
    dimension_summary: dict[str, str] = {}
    by_dim: dict[str, list[Finding]] = {}
    for f in findings:
        by_dim.setdefault(f.dimension, []).append(f)
    for dim, items in by_dim.items():
        worst = min(
            (i.result for i in items),
            key=lambda r: _RESULT_ORDER.index(r),
        )
        n_fail = sum(1 for i in items if i.result != "pass")
        dimension_summary[dim] = f"{worst} ({n_fail}/{len(items)} not passing)"

    return ReviewResult(
        rubric_id=rubric.rubric_id,
        rubric_version=rubric.version,
        deliverable_type=rubric.deliverable_type,
        findings=findings,
        dimension_summary=dimension_summary,
        blockers=blockers,
        majors=majors,
        minors=minors,
        verdict=verdict,
        verdict_rationale=why,
    )


# --------------------------------------------------------------------------- #
# Public entrypoint
# --------------------------------------------------------------------------- #
def review(
    deliverable_text: str,
    rubric: Rubric,
    client: SampleClient,
    *,
    model: str | None = None,
    fallback_model: str | None = None,
    samples: int = 3,
    num_ctx: int = 8192,
    on_criterion: Callable[[dict[str, Any]], None] | None = None,
    failure_modes: list[FailureMode] | None = None,
) -> ReviewResult:
    """Execute ``rubric`` over ``deliverable_text`` and aggregate the result.

    Decomposes the rubric into per-criterion checks (each with self-consistency
    voting + evidence verification), then aggregates deterministically. The
    optional ``on_criterion`` callback receives one trace dict per criterion —
    the worker uses it to write the per-job JSONL traceability log.

    ``failure_modes`` injects library context into every criterion prompt (see
    Phase P2 library loader).
    """
    primary, resolved_fallback = resolve_critic_models(model)
    if fallback_model is not None:
        resolved_fallback = fallback_model

    findings: list[Finding] = []
    for criterion in rubric.criteria:
        finding, trace = check_criterion(
            deliverable_text,
            criterion,
            rubric,
            client,
            primary_model=primary,
            fallback_model=resolved_fallback,
            samples=samples,
            num_ctx=num_ctx,
            failure_modes=failure_modes,
        )
        findings.append(finding)
        if on_criterion is not None:
            on_criterion(trace)

    return aggregate(rubric, findings)
