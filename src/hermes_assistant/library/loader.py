"""Library loader — loads failure modes and exemplars from YAML, caches in memory.

Data lives under ``settings.library_path`` (default:
``src/hermes_assistant/library/data/``) in two subdirectories:

* ``failure_modes/`` — one or more ``*.yaml`` files, each with a top-level
  ``failure_modes:`` list.
* ``exemplars/`` — one or more ``*.yaml`` files, each with a top-level
  ``exemplars:`` list.

New files are picked up with no code changes (mirrors project_types_path
and rubrics_path patterns).  ``load_library()`` is LRU-cached (maxsize=1) so
the YAML is parsed at most once per unique ``base_dir`` per process.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from hermes_assistant.config import settings
from hermes_assistant.library.model import Exemplar, FailureMode, LibraryIndex


class LibraryError(Exception):
    """A library file is missing or malformed."""


def _parse_failure_mode(raw: dict) -> FailureMode:
    """Normalise a YAML failure-mode dict to a :class:`FailureMode`."""
    mit = raw.get("typical_mitigation")
    mitigations: list[str] = (
        [str(mit).strip()] if mit else list(raw.get("mitigations", []))
    )
    return FailureMode(
        id=str(raw["id"]),
        title=str(raw.get("title", "")),
        description=str(raw.get("description", "")).strip(),
        area=str(raw.get("dimension", raw.get("area", ""))),
        severity=str(raw.get("severity", "")),
        mitigations=mitigations,
    )


def _parse_exemplar(raw: dict) -> Exemplar:
    """Normalise a YAML exemplar dict to an :class:`Exemplar`."""
    quality = str(raw.get("quality", ""))
    content = str(raw.get("content", "")).strip()
    return Exemplar(
        id=str(raw["id"]),
        title=str(raw.get("title", "")),
        scenario=str(raw.get("project_type", raw.get("scenario", ""))),
        expected=content if quality == "good" else str(raw.get("expected", "")),
        actual=content if quality == "bad" else str(raw.get("actual", "")),
        lesson=str(raw.get("note", raw.get("lesson", ""))),
    )


def _load_from_dir(base_dir: Path) -> LibraryIndex:
    """Walk ``failure_modes/`` and ``exemplars/`` under *base_dir* and build index."""
    failure_modes: dict[str, FailureMode] = {}
    exemplars: dict[str, Exemplar] = {}

    fm_dir = base_dir / "failure_modes"
    if fm_dir.is_dir():
        for path in sorted(fm_dir.glob("*.y*ml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for item in raw.get("failure_modes", []):
                fm = _parse_failure_mode(item)
                failure_modes[fm.id] = fm

    ex_dir = base_dir / "exemplars"
    if ex_dir.is_dir():
        for path in sorted(ex_dir.glob("*.y*ml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for item in raw.get("exemplars", []):
                ex = _parse_exemplar(item)
                exemplars[ex.id] = ex

    return LibraryIndex(failure_modes=failure_modes, exemplars=exemplars)


@lru_cache(maxsize=8)
def load_library(base_dir: str | None = None) -> LibraryIndex:
    """Load and cache the failure-mode and exemplar library from YAML.

    Args:
        base_dir: Override the library data directory (tests use an explicit
            path so the default settings cache is not poisoned).  ``None``
            uses ``settings.library_path``.

    Returns:
        A :class:`LibraryIndex` with all loaded failure modes and exemplars.
        Returns an empty index if the directory does not exist.
    """
    resolved = Path(base_dir) if base_dir is not None else Path(settings.library_path)
    if not resolved.is_dir():
        return LibraryIndex()
    return _load_from_dir(resolved)
