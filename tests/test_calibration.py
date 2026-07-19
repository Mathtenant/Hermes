"""Unit tests for the calibration module (Phase 4, C2).

Covers loader, metrics, and calibration logic over the shipped
project-plan.gold.yaml fixture. All tests are deterministic and offline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_assistant.calibration.calibrate import calibrate, pair_labels
from hermes_assistant.calibration.loader import (
    CalibrationDataError,
    load_gold,
    load_gold_file,
)
from hermes_assistant.calibration.metrics import (
    cohens_kappa,
    interpret_kappa,
    raw_agreement,
    signed_bias,
)
from hermes_assistant.calibration.model import GoldLabel

# Resolve the shipped fixture path once so tests don't depend on cwd.
_DATA_DIR = Path(__file__).resolve().parent.parent / "src" / "hermes_assistant" / "calibration" / "data"
_GOLD_FILE = _DATA_DIR / "project-plan.gold.yaml"


# ---------------------------------------------------------------------------
# Loader tests
# ---------------------------------------------------------------------------

class TestLoadGoldFile:
    def test_loads_shipped_fixture(self) -> None:
        """The shipped project-plan gold file loads without error."""
        labels = load_gold_file(_GOLD_FILE)
        assert len(labels) > 0
        assert all(isinstance(g, GoldLabel) for g in labels)

    def test_fixture_has_12_items(self) -> None:
        """Fixture has exactly 12 deliverables as documented in the YAML header."""
        labels = load_gold_file(_GOLD_FILE)
        item_ids = {g.item_id for g in labels}
        assert len(item_ids) == 12

    def test_fixture_criteria(self) -> None:
        """Known criteria names are all present in the fixture."""
        expected = {
            "objectives_stated",
            "roles_assigned",
            "deliverables_present",
            "success_metrics_measurable",
            "risk_has_mitigation",
            "risk_has_owner",
            "no_tbd_placeholders",
            "phases_ordered",
        }
        labels = load_gold_file(_GOLD_FILE)
        found = {g.criterion_id for g in labels}
        assert expected == found

    def test_all_results_valid(self) -> None:
        """Every human_result in the fixture is one of pass/partial/fail."""
        labels = load_gold_file(_GOLD_FILE)
        valid = {"pass", "partial", "fail"}
        bad = [g for g in labels if g.human_result not in valid]
        assert bad == []

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        """Loading a non-existent file raises CalibrationDataError."""
        with pytest.raises(CalibrationDataError, match="not found"):
            load_gold_file(tmp_path / "no-such.gold.yaml")

    def test_load_gold_by_rubric_id(self) -> None:
        """load_gold() convenience wrapper works with the data dir."""
        labels = load_gold("project-plan", base_dir=_DATA_DIR)
        assert len(labels) > 0

    def test_load_gold_missing_rubric_raises(self) -> None:
        """Unknown rubric id raises CalibrationDataError."""
        with pytest.raises(CalibrationDataError):
            load_gold("nonexistent-rubric", base_dir=_DATA_DIR)


class TestLoaderEdgeCases:
    def test_malformed_result_raises(self, tmp_path: Path) -> None:
        """A file with an invalid result value raises CalibrationDataError."""
        bad = tmp_path / "bad.gold.yaml"
        bad.write_text(
            "gold:\n  - item_id: x\n    results:\n      c1: maybe\n",
            encoding="utf-8",
        )
        with pytest.raises(CalibrationDataError, match="result must be one of"):
            load_gold_file(bad)

    def test_flat_form_loads(self, tmp_path: Path) -> None:
        """Flat-form gold files (criterion_id + human_result columns) load correctly."""
        flat = tmp_path / "flat.gold.yaml"
        flat.write_text(
            "- item_id: item1\n  criterion_id: c1\n  human_result: pass\n",
            encoding="utf-8",
        )
        labels = load_gold_file(flat)
        assert len(labels) == 1
        assert labels[0].human_result == "pass"
        assert labels[0].criterion_id == "c1"


# ---------------------------------------------------------------------------
# Metrics tests
# ---------------------------------------------------------------------------

class TestRawAgreement:
    def test_perfect_agreement(self) -> None:
        a = ["pass", "fail", "partial"]
        assert raw_agreement(a, a) == 1.0

    def test_no_agreement(self) -> None:
        a = ["pass", "pass"]
        b = ["fail", "fail"]
        assert raw_agreement(a, b) == 0.0

    def test_partial_agreement(self) -> None:
        a = ["pass", "fail"]
        b = ["pass", "pass"]
        assert raw_agreement(a, b) == 0.5

    def test_empty_returns_zero(self) -> None:
        assert raw_agreement([], []) == 0.0

    def test_mismatched_lengths_raise(self) -> None:
        with pytest.raises(ValueError):
            raw_agreement(["pass"], ["pass", "fail"])


class TestCohensKappa:
    def test_perfect_agreement_kappa_one(self) -> None:
        a = ["pass"] * 5 + ["fail"] * 5
        assert cohens_kappa(a, a) == pytest.approx(1.0)

    def test_empty_returns_zero(self) -> None:
        assert cohens_kappa([], []) == 0.0

    def test_kappa_below_one_for_partial(self) -> None:
        a = ["pass", "pass", "fail", "fail"]
        b = ["pass", "fail", "pass", "fail"]
        k = cohens_kappa(a, b)
        assert -1.0 <= k < 1.0

    def test_degenerate_single_category(self) -> None:
        """When both raters use only one category, kappa is 1 (all match)."""
        a = ["pass", "pass"]
        assert cohens_kappa(a, a) == 1.0


class TestSignedBias:
    def test_no_bias(self) -> None:
        a = ["pass", "fail"]
        assert signed_bias(a, a) == pytest.approx(0.0)

    def test_positive_bias_lenient(self) -> None:
        """Model always grades higher → positive mean gap."""
        model = ["pass", "pass"]
        human = ["fail", "fail"]
        assert signed_bias(model, human) > 0

    def test_negative_bias_severe(self) -> None:
        model = ["fail", "fail"]
        human = ["pass", "pass"]
        assert signed_bias(model, human) < 0

    def test_empty_returns_zero(self) -> None:
        assert signed_bias([], []) == 0.0


class TestInterpretKappa:
    def test_bands(self) -> None:
        assert interpret_kappa(-0.1) == "poor"
        assert interpret_kappa(0.10) == "slight"
        assert interpret_kappa(0.30) == "fair"
        assert interpret_kappa(0.50) == "moderate"
        assert interpret_kappa(0.70) == "substantial"
        assert interpret_kappa(0.90) == "almost perfect"


# ---------------------------------------------------------------------------
# Calibration logic tests
# ---------------------------------------------------------------------------

class TestPairLabels:
    def test_perfect_match(self) -> None:
        gold = [GoldLabel(item_id="i1", criterion_id="c1", human_result="pass")]
        model_results = {("i1", "c1"): "pass"}  # type: ignore[dict-item]
        pairs, unmatched = pair_labels(gold, model_results)
        assert len(pairs) == 1
        assert unmatched == []

    def test_unmatched_recorded(self) -> None:
        gold = [GoldLabel(item_id="i1", criterion_id="c1", human_result="fail")]
        pairs, unmatched = pair_labels(gold, {})
        assert pairs == []
        assert "i1::c1" in unmatched


class TestCalibrateOverFixture:
    """Smoke-test the full calibrate() call over the shipped gold fixture.

    We synthesise a fake model_results dict (all 'pass') to produce a
    deterministic CalibrationReport without needing a live critic run.
    """

    def _load_labels(self) -> list[GoldLabel]:
        return load_gold_file(_GOLD_FILE)

    def test_calibrate_returns_report(self) -> None:
        gold = self._load_labels()
        # Fake perfect-agreement model results
        model_results = {(g.item_id, g.criterion_id): g.human_result for g in gold}
        report = calibrate(
            gold,
            model_results,
            rubric_id="project-plan",
            rubric_version="1",
        )
        assert report.rubric_id == "project-plan"
        assert report.n_items == 12
        assert report.n_pairs == len(gold)
        assert report.overall_agreement == pytest.approx(1.0)
        assert report.meets_target is True

    def test_calibrate_all_pass_no_flags(self) -> None:
        gold = self._load_labels()
        model_results = {(g.item_id, g.criterion_id): g.human_result for g in gold}
        report = calibrate(
            gold,
            model_results,
            rubric_id="project-plan",
            rubric_version="1",
        )
        assert report.flagged_criteria == []

    def test_calibrate_biased_model_flags_criteria(self) -> None:
        """A model that always returns 'pass' on a 'fail' gold set is flagged."""
        gold = self._load_labels()
        # Override all model results to 'pass' (maximum leniency)
        model_results: dict[tuple[str, str], str] = {
            (g.item_id, g.criterion_id): "pass" for g in gold
        }
        report = calibrate(
            gold,
            model_results,  # type: ignore[arg-type]
            rubric_id="project-plan",
            rubric_version="1",
        )
        # Some criteria have fail/partial human labels → model disagrees → flagged
        assert len(report.flagged_criteria) > 0

    def test_calibrate_unmatched_gold_empty_when_all_present(self) -> None:
        gold = self._load_labels()
        model_results = {(g.item_id, g.criterion_id): g.human_result for g in gold}
        report = calibrate(
            gold,
            model_results,
            rubric_id="project-plan",
            rubric_version="1",
        )
        assert report.unmatched_gold == []
