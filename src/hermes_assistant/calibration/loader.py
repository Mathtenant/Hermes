"""Load human gold sets and recorded model results for calibration (C2).

Gold sets are *data*: YAML files named ``{rubric_id}.gold.yaml`` under
``settings.calibration_path``. Two shapes are accepted so authoring is ergonomic:

* a **flat** list of ``{item_id, criterion_id, human_result, note?}`` rows, or
* a **grouped** list of ``{item_id, results: {criterion_id: result, ...}}`` rows,

optionally wrapped in a top-level ``gold:`` (gold files) or ``results:``
(model-result files) mapping key. Malformed rows fail loudly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

from hermes_assistant.calibration.model import GoldLabel, ResultLabel
from hermes_assistant.config import settings

_VALID_RESULTS: frozenset[str] = frozenset({"pass", "partial", "fail"})


class CalibrationDataError(Exception):
    """A gold-set or model-result file is missing or malformed."""


def _base_dir(base_dir: str | Path | None) -> Path:
    return Path(base_dir) if base_dir is not None else Path(settings.calibration_path)


def _validate_result(value: Any, where: str) -> ResultLabel:
    if value not in _VALID_RESULTS:
        raise CalibrationDataError(
            f"{where}: result must be one of {sorted(_VALID_RESULTS)}, got {value!r}"
        )
    return cast(ResultLabel, value)


def _rows(raw: Any, key: str, path_name: str) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        items = raw.get(key, [])
    elif isinstance(raw, list):
        items = raw
    else:
        raise CalibrationDataError(
            f"{path_name}: expected a list or a mapping with '{key}:', "
            f"got {type(raw).__name__}"
        )
    if not isinstance(items, list):
        raise CalibrationDataError(f"{path_name}: '{key}' must be a list")
    for item in items:
        if not isinstance(item, dict):
            raise CalibrationDataError(f"{path_name}: each row must be a mapping")
    return items


def _expand(
    rows: list[dict[str, Any]], result_field: str, path_name: str
) -> list[tuple[str, str, ResultLabel, str]]:
    """Normalise flat and grouped rows to ``(item_id, criterion_id, result, note)``."""
    out: list[tuple[str, str, ResultLabel, str]] = []
    for row in rows:
        item_id = row.get("item_id")
        if not item_id:
            raise CalibrationDataError(f"{path_name}: row missing 'item_id'")
        note = str(row.get("note", ""))
        if "results" in row:  # grouped form
            results = row["results"]
            if not isinstance(results, dict):
                raise CalibrationDataError(
                    f"{path_name}: '{item_id}'.results must be a mapping"
                )
            for criterion_id, value in results.items():
                where = f"{path_name}:{item_id}.{criterion_id}"
                out.append((str(item_id), str(criterion_id),
                            _validate_result(value, where), note))
        else:  # flat form
            criterion_id = row.get("criterion_id")
            if not criterion_id:
                raise CalibrationDataError(
                    f"{path_name}: '{item_id}' row missing 'criterion_id'"
                )
            value = row.get(result_field)
            where = f"{path_name}:{item_id}.{criterion_id}"
            out.append((str(item_id), str(criterion_id),
                        _validate_result(value, where), note))
    return out


def load_gold_file(path: str | Path) -> list[GoldLabel]:
    """Load human gold labels from one YAML file."""
    p = Path(path)
    if not p.is_file():
        raise CalibrationDataError(f"gold set not found: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    rows = _rows(raw, "gold", p.name)
    return [
        GoldLabel(item_id=i, criterion_id=c, human_result=r, note=note)
        for i, c, r, note in _expand(rows, "human_result", p.name)
    ]


def load_gold(rubric_id: str, base_dir: str | Path | None = None) -> list[GoldLabel]:
    """Load the gold set shipped for ``rubric_id`` (``{rubric_id}.gold.yaml``)."""
    path = _base_dir(base_dir) / f"{rubric_id}.gold.yaml"
    return load_gold_file(path)


def load_model_results_file(
    path: str | Path,
) -> dict[tuple[str, str], ResultLabel]:
    """Load recorded model results, keyed by ``(item_id, criterion_id)``.

    Accepts ``model_result`` or ``result`` as the value field (grouped rows use
    the mapping value directly).
    """
    p = Path(path)
    if not p.is_file():
        raise CalibrationDataError(f"model results not found: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    rows = _rows(raw, "results", p.name)
    field = "model_result"
    if rows and "results" not in rows[0] and "model_result" not in rows[0]:
        field = "result"
    out: dict[tuple[str, str], ResultLabel] = {}
    for item_id, criterion_id, result, _note in _expand(rows, field, p.name):
        out[(item_id, criterion_id)] = result
    return out
