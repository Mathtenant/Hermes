"""Rubric loader with filename-based version resolution.

Rubrics ship as YAML data files named ``{rubric_id}.v{N}.yaml`` under
``settings.rubrics_path``. New rubrics (or new versions) are added as files
with no code changes — the same data-driven pattern as ``project_types``.

``load_rubric(id)`` resolves to the highest available version; a specific
version can be pinned. Duplicate criterion ids are rejected at load time so a
malformed rubric fails loudly rather than silently double-counting.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

from hermes_assistant.config import settings
from hermes_assistant.rubrics.model import Rubric

# Matches "project-plan.v1.yaml" -> id="project-plan", version="1".
_FILENAME_RE = re.compile(r"^(?P<id>.+)\.v(?P<ver>\d+)\.ya?ml$")


class RubricError(Exception):
    """A rubric file is missing, malformed, or internally inconsistent."""


def _base_dir(base_dir: str | Path | None) -> Path:
    return Path(base_dir) if base_dir is not None else Path(settings.rubrics_path)


def _normalise_version(version: str | int | None) -> str | None:
    """Accept ``1``, ``"1"`` or ``"v1"`` (or ``None``) -> canonical ``"1"``."""
    if version is None:
        return None
    text = str(version).strip().lower()
    if text.startswith("v"):
        text = text[1:]
    return text


def _discover(base_dir: str | Path | None = None) -> dict[str, dict[str, Path]]:
    """Map ``rubric_id -> {version: path}`` for every rubric YAML on disk."""
    directory = _base_dir(base_dir)
    found: dict[str, dict[str, Path]] = {}
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("*.y*ml")):
        match = _FILENAME_RE.match(path.name)
        if not match:
            continue
        found.setdefault(match["id"], {})[match["ver"]] = path
    return found


def list_rubrics(base_dir: str | Path | None = None) -> list[tuple[str, str]]:
    """Return ``(rubric_id, version)`` pairs for all rubrics, sorted."""
    pairs: list[tuple[str, str]] = []
    for rubric_id, versions in _discover(base_dir).items():
        for version in versions:
            pairs.append((rubric_id, version))
    return sorted(pairs, key=lambda p: (p[0], int(p[1])))


def _validate(rubric: Rubric, source: Path) -> Rubric:
    """Reject duplicate criterion / anti-pattern ids (single source of truth)."""
    crit_ids = [c.id for c in rubric.criteria]
    dupes = {i for i in crit_ids if crit_ids.count(i) > 1}
    if dupes:
        raise RubricError(
            f"Duplicate criterion id(s) {sorted(dupes)} in {source.name}"
        )
    ap_ids = [a.id for a in rubric.anti_patterns]
    ap_dupes = {i for i in ap_ids if ap_ids.count(i) > 1}
    if ap_dupes:
        raise RubricError(
            f"Duplicate anti-pattern id(s) {sorted(ap_dupes)} in {source.name}"
        )
    if not rubric.criteria:
        raise RubricError(f"Rubric {source.name} declares no criteria")
    return rubric


def load_rubric(
    rubric_id: str,
    version: str | int | None = None,
    base_dir: str | Path | None = None,
) -> Rubric:
    """Load a rubric by id, resolving to the highest version unless pinned.

    Args:
        rubric_id: The rubric id (e.g. ``"project-plan"``).
        version: Pin a specific version (``1``/``"1"``/``"v1"``); ``None`` picks
            the highest available.
        base_dir: Override the rubric data directory (tests).

    Raises:
        RubricError: If no matching rubric exists or the file is inconsistent.
    """
    versions = _discover(base_dir).get(rubric_id)
    if not versions:
        available = ", ".join(sorted({r for r, _ in list_rubrics(base_dir)})) or "(none)"
        raise RubricError(f"Unknown rubric {rubric_id!r}. Available: {available}")

    wanted = _normalise_version(version)
    if wanted is None:
        chosen = max(versions, key=int)
    elif wanted in versions:
        chosen = wanted
    else:
        have = ", ".join(sorted(versions, key=int))
        raise RubricError(
            f"Rubric {rubric_id!r} has no version {wanted!r}. Available: {have}"
        )

    path = versions[chosen]
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    try:
        rubric = Rubric.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 — re-raise as a domain error
        raise RubricError(f"Malformed rubric {path.name}: {exc}") from exc
    return _validate(rubric, path)


@lru_cache(maxsize=1)
def default_rubric_id() -> str:
    """Return a deterministic fallback rubric id (first available)."""
    ids = sorted({r for r, _ in list_rubrics()})
    return ids[0] if ids else "project-plan"
