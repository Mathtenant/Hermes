"""Panel vs. single-judge evaluation harness (Phase P5d).

Computes Cohen's κ for both the single-judge and the panel against a human
gold set, then determines whether the panel measurably beats the single judge.

The evaluation is purely statistical: it takes pre-computed result dicts
(one per judging mode) and compares them against the human gold labels.
No model inference is performed here.

Usage pattern::

    gold = calibration.loader.load_gold("project-plan")
    # Collect single-judge and panel results from completed jobs…
    report = evaluate_panel_vs_single(
        gold=gold,
        single_results={(item_id, criterion_id): result, …},
        panel_results={(item_id, criterion_id): result, …},
        rubric_id="project-plan",
    )
    if report.panel_wins:
        print("Panel beats single-judge — consider enabling by default")

Panel is off by default and must demonstrably beat the single judge on Cohen's
κ before it can be considered for production.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from hermes_assistant.calibration.metrics import cohens_kappa, raw_agreement
from hermes_assistant.calibration.model import GoldLabel

# Shorthand for the three-class result vocabulary.
_ResultStr = Literal["pass", "partial", "fail"]


class PanelEvalReport(BaseModel):
    """Comparison report: panel vs. single-judge against a human gold set."""

    rubric_id: str
    n_gold_pairs: int        # (item, criterion) pairs tested (matched in all three sources)
    single_judge_kappa: float   # Cohen's κ for single-judge vs. gold
    panel_kappa: float           # Cohen's κ for panel vs. gold
    single_judge_agreement: float  # raw % agreement for single-judge vs. gold
    panel_agreement: float         # raw % agreement for panel vs. gold
    delta_kappa: float             # panel_kappa - single_judge_kappa
    panel_wins: bool               # delta_kappa > 0 (strictly, pessimistic tie)
    recommendation: Literal["keep_panel", "keep_single_judge"]


def evaluate_panel_vs_single(
    gold: list[GoldLabel],
    single_results: dict[tuple[str, str], _ResultStr],
    panel_results: dict[tuple[str, str], _ResultStr],
    *,
    rubric_id: str,
) -> PanelEvalReport:
    """Evaluate panel against single-judge on a human gold set.

    Only (item_id, criterion_id) pairs that appear in **all three** sources
    (gold, single_results, panel_results) are included in the comparison.
    Unmatched cells are silently excluded; ``n_gold_pairs`` reflects this count.

    Args:
        gold: Human-graded labels (list of :class:`GoldLabel`).
        single_results: Single-judge results keyed by (item_id, criterion_id).
        panel_results: Panel results keyed by (item_id, criterion_id).
        rubric_id: Rubric ID for the report header.

    Returns:
        :class:`PanelEvalReport` with κ comparison and a recommendation.
        When ``n_gold_pairs == 0`` (no matched cells), all metrics are 0 and
        the recommendation is ``"keep_single_judge"`` (no evidence to switch).
    """
    # Build gold index
    gold_index: dict[tuple[str, str], str] = {
        (g.item_id, g.criterion_id): g.human_result for g in gold
    }

    # Find common keys: present in gold AND single AND panel
    common_keys = [
        key
        for key in gold_index
        if key in single_results and key in panel_results
    ]
    n = len(common_keys)

    if n == 0:
        return PanelEvalReport(
            rubric_id=rubric_id,
            n_gold_pairs=0,
            single_judge_kappa=0.0,
            panel_kappa=0.0,
            single_judge_agreement=0.0,
            panel_agreement=0.0,
            delta_kappa=0.0,
            panel_wins=False,
            recommendation="keep_single_judge",
        )

    human_labels = [gold_index[k] for k in common_keys]
    single_labels = [single_results[k] for k in common_keys]
    panel_labels = [panel_results[k] for k in common_keys]

    sk = cohens_kappa(single_labels, human_labels)
    pk = cohens_kappa(panel_labels, human_labels)
    sa = raw_agreement(single_labels, human_labels)
    pa = raw_agreement(panel_labels, human_labels)

    delta = pk - sk
    panel_wins = delta > 0  # strictly positive; ties are pessimistic

    return PanelEvalReport(
        rubric_id=rubric_id,
        n_gold_pairs=n,
        single_judge_kappa=round(sk, 6),
        panel_kappa=round(pk, 6),
        single_judge_agreement=round(sa, 6),
        panel_agreement=round(pa, 6),
        delta_kappa=round(delta, 6),
        panel_wins=panel_wins,
        recommendation="keep_panel" if panel_wins else "keep_single_judge",
    )
