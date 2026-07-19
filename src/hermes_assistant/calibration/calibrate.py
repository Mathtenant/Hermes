"""Calibrate the rubric critic against a human-graded gold set (Phase 4, C2).

Given model results and human gold labels for the same (deliverable, criterion)
cells, produce a :class:`CalibrationReport`: overall judge-human agreement
(Cohen's kappa vs a target), and — per criterion — agreement, a leniency/severity
bias, and a *flag* marking where model and human disagree enough that the rubric
wording should be fixed (the actionable output the spec asks for).

Pure Python and deterministic: no model is called here.
"""

from __future__ import annotations

from hermes_assistant.calibration.metrics import (
    cohens_kappa,
    raw_agreement,
    signed_bias,
)
from hermes_assistant.calibration.model import (
    BiasDirection,
    CalibrationPair,
    CalibrationReport,
    CriterionCalibration,
    GoldLabel,
    ResultLabel,
)

# A per-criterion agreement below this, OR a directional bias at/above the
# magnitude threshold, flags the criterion for rubric-wording review.
_FLAG_AGREEMENT_BELOW = 0.80
_FLAG_BIAS_MAGNITUDE = 0.50


def pair_labels(
    gold: list[GoldLabel],
    model_results: dict[tuple[str, str], ResultLabel],
) -> tuple[list[CalibrationPair], list[str]]:
    """Join gold labels to recorded model results by (item_id, criterion_id).

    Returns ``(pairs, unmatched)`` where ``unmatched`` lists the
    ``"item_id::criterion_id"`` gold cells that have no recorded model result
    (these are excluded from the metrics rather than silently guessed).
    """
    pairs: list[CalibrationPair] = []
    unmatched: list[str] = []
    for g in gold:
        key = (g.item_id, g.criterion_id)
        model_result = model_results.get(key)
        if model_result is None:
            unmatched.append(f"{g.item_id}::{g.criterion_id}")
            continue
        pairs.append(
            CalibrationPair(
                item_id=g.item_id,
                criterion_id=g.criterion_id,
                model_result=model_result,
                human_result=g.human_result,
            )
        )
    return pairs, unmatched


def _classify_bias(magnitude: float) -> BiasDirection:
    if magnitude >= _FLAG_BIAS_MAGNITUDE:
        return "lenient"
    if magnitude <= -_FLAG_BIAS_MAGNITUDE:
        return "severe"
    return "aligned"


def _calibrate_criterion(
    criterion_id: str, pairs: list[CalibrationPair]
) -> CriterionCalibration:
    model = [p.model_result for p in pairs]
    human = [p.human_result for p in pairs]
    agreement = raw_agreement(model, human)
    kappa = cohens_kappa(model, human)
    magnitude = signed_bias(model, human)
    bias = _classify_bias(magnitude)
    n_disagree = sum(1 for p in pairs if not p.agree)
    flagged = agreement < _FLAG_AGREEMENT_BELOW or abs(magnitude) >= _FLAG_BIAS_MAGNITUDE
    return CriterionCalibration(
        criterion_id=criterion_id,
        n=len(pairs),
        agreement=round(agreement, 3),
        kappa=round(kappa, 3),
        bias=bias,
        bias_magnitude=round(magnitude, 3),
        n_disagreements=n_disagree,
        flagged=flagged,
    )


def calibrate(
    gold: list[GoldLabel],
    model_results: dict[tuple[str, str], ResultLabel],
    *,
    rubric_id: str,
    rubric_version: str,
    deliverable_type: str = "",
    target_kappa: float = 0.6,
) -> CalibrationReport:
    """Compute a full :class:`CalibrationReport` for one rubric.

    ``gold`` are the human labels; ``model_results`` maps
    ``(item_id, criterion_id) -> model_result`` (e.g. harvested from recorded
    critic findings). Overall kappa is computed across every matched cell; a
    criterion is *flagged* when agreement is low or a systematic
    leniency/severity bias is detected.
    """
    pairs, unmatched = pair_labels(gold, model_results)

    all_model = [p.model_result for p in pairs]
    all_human = [p.human_result for p in pairs]
    overall_agreement = raw_agreement(all_model, all_human)
    overall_kappa = cohens_kappa(all_model, all_human)

    by_criterion_id: dict[str, list[CalibrationPair]] = {}
    for p in pairs:
        by_criterion_id.setdefault(p.criterion_id, []).append(p)

    by_criterion = [
        _calibrate_criterion(cid, cpairs)
        for cid, cpairs in sorted(by_criterion_id.items())
    ]
    flagged = [c.criterion_id for c in by_criterion if c.flagged]
    n_items = len({p.item_id for p in pairs})

    return CalibrationReport(
        rubric_id=rubric_id,
        rubric_version=rubric_version,
        deliverable_type=deliverable_type,
        n_items=n_items,
        n_pairs=len(pairs),
        overall_agreement=round(overall_agreement, 3),
        overall_kappa=round(overall_kappa, 3),
        target_kappa=target_kappa,
        meets_target=len(pairs) > 0 and overall_kappa >= target_kappa,
        by_criterion=by_criterion,
        flagged_criteria=flagged,
        unmatched_gold=unmatched,
    )
