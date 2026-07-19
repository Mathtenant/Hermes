"""Project-type taxonomy loader & resolver tests (offline, data-driven)."""

import pytest

from hermes_assistant.hermes.project_types import (
    list_project_types,
    load_phase_spine,
    load_project_type,
    mandatory_deliverables,
    resolve_phases,
)


def test_list_project_types_includes_isds() -> None:
    """The shipped taxonomy exposes the ISDS seed and excludes the spine file."""
    types = list_project_types()
    assert "isds-analyse" in types
    assert all(not t.startswith("_") for t in types)


def test_load_project_type_fields() -> None:
    """ISDS type carries its minimum roles and deliverables."""
    pt = load_project_type("isds-analyse")
    assert pt.min_roles == ["Auftraggeber", "Projektleiter", "ISBO"]
    ids = {d.id for d in pt.deliverables}
    assert {"informatikschutzobjekt", "schutzbedarf", "risikoanalyse", "massnahmen"} <= ids


def test_load_unknown_type_raises() -> None:
    """An unknown type id raises FileNotFoundError with the available list."""
    with pytest.raises(FileNotFoundError):
        load_project_type("does-not-exist")


def test_phase_spine_ordered() -> None:
    """The generic spine has the three ordered HERMES phases with gates."""
    spine = load_phase_spine()
    assert list(spine) == ["initiation", "analysis", "concept"]
    assert all(any(m.is_quality_gate for m in p.milestones) for p in spine.values())


def test_resolve_phases_preserves_declared_order() -> None:
    """resolve_phases returns the type's phases in declared order."""
    pt = load_project_type("isds-analyse")
    ordered = [p.id for p in resolve_phases(pt)]
    assert ordered == ["initiation", "analysis", "concept"]


def test_mandatory_deliverables_without_flags() -> None:
    """With no sizing flags, only the four unconditional deliverables are mandatory."""
    pt = load_project_type("isds-analyse")
    ids = [d.id for d in mandatory_deliverables(pt, {})]
    assert ids == ["informatikschutzobjekt", "schutzbedarf", "risikoanalyse", "massnahmen"]


def test_mandatory_deliverables_conditional_flag_adds_restrisiko() -> None:
    """Setting high_protection_need promotes the conditional Restrisiko-Freigabe."""
    pt = load_project_type("isds-analyse")
    ids = {d.id for d in mandatory_deliverables(pt, {"high_protection_need": True})}
    assert "restrisiko_freigabe" in ids


def test_mandatory_deliverables_flag_false_excludes() -> None:
    """An explicitly-false flag keeps the conditional deliverable out."""
    pt = load_project_type("isds-analyse")
    ids = {d.id for d in mandatory_deliverables(pt, {"high_protection_need": False})}
    assert "restrisiko_freigabe" not in ids
