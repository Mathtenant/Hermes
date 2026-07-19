"""Phase P5d tests — PanelEvalReport, evaluate_panel_vs_single, CLI panel-eval.

All tests are purely deterministic: no LLM, no network, no file I/O beyond
what the test itself writes via tmp_path.
"""

from __future__ import annotations

import json
from pathlib import Path

from hermes_assistant.agents.panel_eval import evaluate_panel_vs_single
from hermes_assistant.calibration.model import GoldLabel

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _gold(*pairs: tuple[str, str, str]) -> list[GoldLabel]:
    """Build a gold list from (item_id, criterion_id, human_result) triples."""
    return [GoldLabel(item_id=i, criterion_id=c, human_result=r) for i, c, r in pairs]


def _results(*pairs: tuple[str, str, str]) -> dict[tuple[str, str], str]:
    """Build a results dict from (item_id, criterion_id, result) triples."""
    return {(i, c): r for i, c, r in pairs}


# --------------------------------------------------------------------------- #
# Unit tests for evaluate_panel_vs_single
# --------------------------------------------------------------------------- #

def test_panel_wins_when_higher_kappa() -> None:
    """When the panel's κ is strictly higher than the single judge's, panel_wins=True."""
    gold = _gold(
        ("i1", "c1", "pass"),
        ("i2", "c1", "fail"),
        ("i3", "c1", "partial"),
        ("i4", "c1", "pass"),
    )
    # Single judge: 2/4 correct → lower agreement
    single = _results(
        ("i1", "c1", "pass"),
        ("i2", "c1", "pass"),   # wrong
        ("i3", "c1", "pass"),   # wrong
        ("i4", "c1", "pass"),
    )
    # Panel: 4/4 correct → higher agreement
    panel = _results(
        ("i1", "c1", "pass"),
        ("i2", "c1", "fail"),
        ("i3", "c1", "partial"),
        ("i4", "c1", "pass"),
    )
    report = evaluate_panel_vs_single(
        gold=gold, single_results=single, panel_results=panel, rubric_id="test"
    )
    assert report.panel_wins is True
    assert report.recommendation == "keep_panel"
    assert report.delta_kappa > 0


def test_single_wins_when_higher_kappa() -> None:
    """When the single judge's κ is higher, panel_wins=False (pessimistic)."""
    gold = _gold(
        ("i1", "c1", "pass"),
        ("i2", "c1", "fail"),
        ("i3", "c1", "partial"),
        ("i4", "c1", "pass"),
    )
    # Single judge: perfect
    single = _results(
        ("i1", "c1", "pass"),
        ("i2", "c1", "fail"),
        ("i3", "c1", "partial"),
        ("i4", "c1", "pass"),
    )
    # Panel: worse
    panel = _results(
        ("i1", "c1", "pass"),
        ("i2", "c1", "pass"),   # wrong
        ("i3", "c1", "pass"),   # wrong
        ("i4", "c1", "pass"),
    )
    report = evaluate_panel_vs_single(
        gold=gold, single_results=single, panel_results=panel, rubric_id="test"
    )
    assert report.panel_wins is False
    assert report.recommendation == "keep_single_judge"
    assert report.delta_kappa < 0


def test_tie_is_pessimistic() -> None:
    """When both judges agree identically (Δκ == 0), panel_wins=False (pessimistic tie)."""
    gold = _gold(("i1", "c1", "pass"), ("i2", "c1", "fail"))
    labels = _results(("i1", "c1", "pass"), ("i2", "c1", "fail"))
    report = evaluate_panel_vs_single(
        gold=gold,
        single_results=labels,
        panel_results=labels.copy(),
        rubric_id="test",
    )
    # delta_kappa == 0; pessimistic → not a win
    assert report.delta_kappa == 0.0
    assert report.panel_wins is False
    assert report.recommendation == "keep_single_judge"


def test_empty_gold_returns_zero_report() -> None:
    """An empty gold list (or no common keys) returns a zero report with keep_single_judge."""
    report = evaluate_panel_vs_single(
        gold=[],
        single_results={},
        panel_results={},
        rubric_id="empty",
    )
    assert report.n_gold_pairs == 0
    assert report.panel_wins is False
    assert report.recommendation == "keep_single_judge"
    assert report.single_judge_kappa == 0.0
    assert report.panel_kappa == 0.0


def test_unmatched_keys_excluded() -> None:
    """Pairs not present in all three sources are silently excluded; n_gold_pairs reflects this."""
    gold = _gold(
        ("i1", "c1", "pass"),
        ("i2", "c1", "fail"),  # missing from single → excluded
    )
    single = _results(("i1", "c1", "pass"))       # only i1
    panel = _results(("i1", "c1", "pass"), ("i2", "c1", "fail"))
    report = evaluate_panel_vs_single(
        gold=gold, single_results=single, panel_results=panel, rubric_id="test"
    )
    assert report.n_gold_pairs == 1   # only (i1, c1) is common to all three


def test_report_rubric_id_preserved() -> None:
    """rubric_id from the call argument is passed through to the report."""
    gold = _gold(("i1", "c1", "pass"))
    r = _results(("i1", "c1", "pass"))
    report = evaluate_panel_vs_single(
        gold=gold, single_results=r, panel_results=r.copy(), rubric_id="my-rubric"
    )
    assert report.rubric_id == "my-rubric"


# --------------------------------------------------------------------------- #
# CLI integration tests (Typer runner, no live Ollama)
# --------------------------------------------------------------------------- #

def _write_gold(tmp_path: Path, rubric_id: str) -> Path:
    """Write a minimal .gold.yaml for load_gold() to find."""
    from hermes_assistant.config import settings

    base = Path(settings.calibration_path)
    gold_file = base / f"{rubric_id}.gold.yaml"
    gold_file.parent.mkdir(parents=True, exist_ok=True)
    gold_file.write_text(
        "- item_id: i1\n  criterion_id: c1\n  human_result: pass\n"
        "- item_id: i2\n  criterion_id: c1\n  human_result: fail\n",
        encoding="utf-8",
    )
    return gold_file


def _write_results(tmp_path: Path, name: str, data: dict[str, str]) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_cli_panel_eval_success(tmp_path: Path) -> None:
    """panel-eval exits 0 when panel beats single judge."""
    from typer.testing import CliRunner

    from hermes_assistant.cli import app

    rubric_id = "cli-test-win"
    gold_file = _write_gold(tmp_path, rubric_id)
    # Panel is perfect; single misses one
    single_path = _write_results(tmp_path, "single.json", {
        "i1|c1": "pass",
        "i2|c1": "pass",  # wrong: gold is fail
    })
    panel_path = _write_results(tmp_path, "panel.json", {
        "i1|c1": "pass",
        "i2|c1": "fail",  # correct
    })
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "panel-eval", rubric_id,
            "--single-results", str(single_path),
            "--panel-results", str(panel_path),
        ],
        catch_exceptions=False,
    )
    # Clean up the file we wrote to the shared calibration path
    gold_file.unlink(missing_ok=True)
    assert result.exit_code == 0, result.output
    assert "keep_panel" in result.output.upper() or "KEEP PANEL" in result.output.upper()


def test_cli_panel_eval_fail(tmp_path: Path) -> None:
    """panel-eval exits 1 when single judge beats panel (pessimistic)."""
    from typer.testing import CliRunner

    from hermes_assistant.cli import app

    rubric_id = "cli-test-lose"
    gold_file = _write_gold(tmp_path, rubric_id)
    # Single is perfect; panel misses one
    single_path = _write_results(tmp_path, "single.json", {
        "i1|c1": "pass",
        "i2|c1": "fail",  # correct
    })
    panel_path = _write_results(tmp_path, "panel.json", {
        "i1|c1": "pass",
        "i2|c1": "pass",  # wrong: gold is fail
    })
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "panel-eval", rubric_id,
            "--single-results", str(single_path),
            "--panel-results", str(panel_path),
        ],
        catch_exceptions=False,
    )
    gold_file.unlink(missing_ok=True)
    assert result.exit_code == 1, result.output
    assert (
        "keep_single_judge" in result.output.lower()
        or "KEEP SINGLE" in result.output.upper()
    )
