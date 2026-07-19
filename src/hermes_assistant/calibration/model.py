"""Flat Pydantic models for judge calibration (Phase 4, C2).

All models are flat / non-recursive (Phase 4 invariant). The per-criterion
result vocabulary (``pass`` | ``partial`` | ``fail``) is the same one the critic
emits on :class:`~hermes_assistant.hermes.model.Finding`, so a recorded review
label and a human gold label are directly comparable.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# Same three-class vocabulary the critic emits per criterion.
ResultLabel = Literal["pass", "partial", "fail"]

# Direction of a systematic judge bias relative to the human gold labels.
#   lenient -> the model grades HIGHER than humans (passes what humans failed)
#   severe  -> the model grades LOWER  than humans (fails what humans passed)
#   aligned -> no material directional bias
BiasDirection = Literal["aligned", "lenient", "severe"]


class GoldLabel(BaseModel):
    """One human-graded criterion result for one deliverable (a gold datum)."""

    item_id: str
    criterion_id: str
    human_result: ResultLabel
    note: str = ""


class CalibrationPair(BaseModel):
    """A model result paired with its human gold label for the same criterion."""

    item_id: str
    criterion_id: str
    model_result: ResultLabel
    human_result: ResultLabel

    @property
    def agree(self) -> bool:
        return self.model_result == self.human_result


class CriterionCalibration(BaseModel):
    """Agreement statistics for a single rubric criterion."""

    criterion_id: str
    n: int
    agreement: float  # raw fraction of matching labels [0, 1]
    kappa: float  # Cohen's kappa for this criterion [-1, 1]
    bias: BiasDirection
    bias_magnitude: float  # mean signed ordinal gap (model - human)
    n_disagreements: int
    flagged: bool  # rubric wording likely needs fixing here


class CalibrationReport(BaseModel):
    """Aggregated judge-vs-human calibration result for one rubric."""

    rubric_id: str
    rubric_version: str
    deliverable_type: str = ""
    n_items: int  # distinct deliverables in the gold set
    n_pairs: int  # criterion-level comparisons
    overall_agreement: float
    overall_kappa: float
    target_kappa: float
    meets_target: bool
    by_criterion: list[CriterionCalibration] = []
    flagged_criteria: list[str] = []
    unmatched_gold: list[str] = []  # gold labels with no recorded model result
