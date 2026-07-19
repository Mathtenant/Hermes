"""Deterministic agreement metrics for judge calibration (Phase 4, C2).

Pure functions only — no LLM, no I/O. Cohen's kappa corrects raw agreement for
the agreement expected by chance, which matters for skewed label distributions
(e.g. a criterion that almost everyone passes). Ordinal helpers give the
*direction* of disagreement (leniency vs severity) rather than just its size.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from hermes_assistant.calibration.model import ResultLabel

# fail < partial < pass — ordinal scale so we can measure the *direction* of a
# disagreement (a positive model-minus-human gap == the model graded higher).
_ORDINAL: dict[str, int] = {"fail": 0, "partial": 1, "pass": 2}


def ordinal(label: str) -> int:
    """Map a result label onto the fail<partial<pass ordinal scale."""
    return _ORDINAL[label]


def raw_agreement(a: Sequence[str], b: Sequence[str]) -> float:
    """Fraction of positions where the two label sequences match.

    Empty input yields ``0.0`` (nothing observed, no agreement claimed).
    """
    if len(a) != len(b):
        raise ValueError("label sequences must be the same length")
    if not a:
        return 0.0
    matches = sum(1 for x, y in zip(a, b, strict=True) if x == y)
    return matches / len(a)


def cohens_kappa(a: Sequence[str], b: Sequence[str]) -> float:
    """Cohen's kappa between two raters' label sequences.

    ``a`` and ``b`` are aligned label lists (rater A vs rater B). Returns a value
    in ``[-1, 1]``; ``1`` is perfect agreement, ``0`` is chance-level.

    Degenerate case: when chance agreement ``p_e`` is 1.0 (both raters used a
    single, identical category) kappa is undefined by the formula; we return
    ``1.0`` if the raters agree everywhere and ``0.0`` otherwise, which is the
    conventional resolution.
    """
    if len(a) != len(b):
        raise ValueError("label sequences must be the same length")
    n = len(a)
    if n == 0:
        return 0.0

    p_o = raw_agreement(a, b)

    count_a = Counter(a)
    count_b = Counter(b)
    categories = set(count_a) | set(count_b)
    p_e = sum((count_a[c] / n) * (count_b[c] / n) for c in categories)

    if p_e >= 1.0:
        return 1.0 if p_o >= 1.0 else 0.0
    return (p_o - p_e) / (1.0 - p_e)


def signed_bias(model: Sequence[str], human: Sequence[str]) -> float:
    """Mean signed ordinal gap ``model - human`` over aligned labels.

    Positive => the model grades higher than humans on average (leniency);
    negative => the model grades lower (severity); ~zero => aligned.
    """
    if len(model) != len(human):
        raise ValueError("label sequences must be the same length")
    if not model:
        return 0.0
    gaps = [ordinal(m) - ordinal(h) for m, h in zip(model, human, strict=True)]
    return sum(gaps) / len(gaps)


def interpret_kappa(kappa: float) -> str:
    """Landis & Koch band label for a kappa value (for human-readable reports)."""
    if kappa < 0.0:
        return "poor"
    if kappa < 0.20:
        return "slight"
    if kappa < 0.40:
        return "fair"
    if kappa < 0.60:
        return "moderate"
    if kappa < 0.80:
        return "substantial"
    return "almost perfect"


def _assert_labels(labels: Sequence[str]) -> None:
    """Guard: every label must be a known result class (fail-loud validation)."""
    unknown = {x for x in labels if x not in _ORDINAL}
    if unknown:
        raise ValueError(f"unknown result label(s): {sorted(unknown)}")


def validated_pair(model: Sequence[ResultLabel], human: Sequence[ResultLabel]) -> None:
    """Validate a model/human label pairing at a system boundary."""
    _assert_labels(model)
    _assert_labels(human)
    if len(model) != len(human):
        raise ValueError("model and human label sequences must be the same length")
