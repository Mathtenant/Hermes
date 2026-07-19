"""Pydantic models for the failure-mode and exemplar library (Phase P2)."""

from __future__ import annotations

from pydantic import BaseModel


class FailureMode(BaseModel):
    """A named failure pattern extracted from project post-mortems.

    Loaded from ``library/data/failure_modes/*.yaml``. Fields map the YAML
    vocabulary (``dimension`` -> ``area``, ``typical_mitigation`` -> first
    element of ``mitigations``).
    """

    id: str
    title: str
    description: str
    area: str = ""
    severity: str = ""
    mitigations: list[str] = []


class Exemplar(BaseModel):
    """A paired good/bad deliverable fragment with an extracted lesson.

    Loaded from ``library/data/exemplars/*.yaml``.  The loader populates
    ``expected`` for quality=good records and ``actual`` for quality=bad records.
    """

    id: str
    title: str
    scenario: str = ""   # project_type in YAML
    expected: str = ""   # content of the good variant
    actual: str = ""     # content of the bad variant
    lesson: str = ""     # note in YAML


class LibraryIndex(BaseModel):
    """In-memory index of all loaded library items, keyed by id."""

    failure_modes: dict[str, FailureMode] = {}
    exemplars: dict[str, Exemplar] = {}
