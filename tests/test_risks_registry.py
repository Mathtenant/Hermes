"""Risk registry tests — CRUD, auto-creation, filtering, sorting, persistence, confidentiality.

54 tests covering every public method of RiskRegistry.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from hermes_assistant.risks.model import Risk, RiskSeverity, RiskStatus
from hermes_assistant.risks.registry import RiskNotFoundError, RiskRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reg(tmp_path: Path) -> RiskRegistry:
    return RiskRegistry(tmp_path / "risks.db")


def _mem() -> RiskRegistry:
    return RiskRegistry(":memory:")


# ---------------------------------------------------------------------------
# CRUD — create (10 tests)
# ---------------------------------------------------------------------------

def test_create_returns_risk(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Budget overrun")
    assert isinstance(r, Risk)


def test_create_auto_assigns_id(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Budget overrun")
    assert r.id and len(r.id) == 32  # uuid4 hex


def test_create_default_status_open(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Budget overrun")
    assert r.status is RiskStatus.open


def test_create_default_severity_medium(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Budget overrun")
    assert r.severity is RiskSeverity.medium


def test_create_default_likelihood(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Budget overrun")
    assert r.likelihood == 3


def test_create_stores_title(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Vendor delay")
    assert r.title == "Vendor delay"


def test_create_stores_description(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Vendor delay", description="Third-party software may slip by 2 weeks.")
    assert "slip" in r.description


def test_create_stores_owner(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Key person", owner="Alice")
    assert r.owner == "Alice"


def test_create_stores_severity(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Key person", severity=RiskSeverity.critical)
    assert r.severity is RiskSeverity.critical


def test_create_stores_likelihood(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Key person", likelihood=4)
    assert r.likelihood == 4


# ---------------------------------------------------------------------------
# CRUD — get / update / delete (10 tests)
# ---------------------------------------------------------------------------

def test_get_returns_created_risk(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Scope creep")
    got = reg.get(r.id)
    assert got is not None
    assert got.id == r.id
    assert got.title == "Scope creep"


def test_get_missing_returns_none(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    assert reg.get("nonexistent") is None


def test_update_title(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Scope creep")
    reg.update(r.id, title="Scope expansion")
    assert reg.get(r.id).title == "Scope expansion"  # type: ignore[union-attr]


def test_update_severity(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Scope creep")
    reg.update(r.id, severity=RiskSeverity.high)
    assert reg.get(r.id).severity is RiskSeverity.high  # type: ignore[union-attr]


def test_update_status(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Scope creep")
    reg.update(r.id, status=RiskStatus.mitigated)
    assert reg.get(r.id).status is RiskStatus.mitigated  # type: ignore[union-attr]


def test_update_owner(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Scope creep")
    reg.update(r.id, owner="Bob")
    assert reg.get(r.id).owner == "Bob"  # type: ignore[union-attr]


def test_update_returns_updated_risk(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Scope creep")
    updated = reg.update(r.id, title="New title")
    assert isinstance(updated, Risk)
    assert updated.title == "New title"


def test_update_missing_raises(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    with pytest.raises(RiskNotFoundError):
        reg.update("nosuchrisk", title="x")


def test_delete_removes_risk(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Temp risk")
    assert reg.delete(r.id) is True
    assert reg.get(r.id) is None


def test_delete_missing_returns_false(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    assert reg.delete("nosuchrisk") is False


# ---------------------------------------------------------------------------
# Auto-creation (5 tests)
# ---------------------------------------------------------------------------

def test_auto_create_from_text(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.auto_create("Budget overrun\nThe project may exceed its budget by 20%.")
    assert isinstance(r, Risk)


def test_auto_create_extracts_title(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.auto_create("Vendor delay\nSupplier may not deliver on time.")
    assert r.title == "Vendor delay"


def test_auto_create_sets_description(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.auto_create("Vendor delay\nSupplier may not deliver on time.")
    assert "deliver" in r.description


def test_auto_create_default_severity(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.auto_create("Minor paperwork issue\nSome forms may be missing.")
    assert r.severity in list(RiskSeverity)


def test_auto_create_detects_critical_keyword(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.auto_create("Critical data loss\nProduction database might be wiped.")
    assert r.severity is RiskSeverity.critical


# ---------------------------------------------------------------------------
# Filtering (10 tests)
# ---------------------------------------------------------------------------

def test_filter_by_status_open(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Open risk")
    reg.create("Closed risk")
    reg.close(reg.list()[0].id if reg.list()[0].title == "Closed risk" else reg.list()[1].id)
    open_risks = reg.list(status=RiskStatus.open)
    assert all(r.status is RiskStatus.open for r in open_risks)


def test_filter_by_status_closed(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("R1")
    reg.close(r.id)
    reg.create("R2")
    closed = reg.list(status=RiskStatus.closed)
    assert len(closed) == 1
    assert closed[0].id == r.id


def test_filter_by_severity_high(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create("H1", severity=RiskSeverity.high)
    reg.create("L1", severity=RiskSeverity.low)
    highs = reg.list(severity=RiskSeverity.high)
    assert len(highs) == 1
    assert highs[0].title == "H1"


def test_filter_by_severity_critical(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create("C1", severity=RiskSeverity.critical)
    reg.create("M1", severity=RiskSeverity.medium)
    crits = reg.list(severity=RiskSeverity.critical)
    assert all(r.severity is RiskSeverity.critical for r in crits)


def test_filter_by_owner(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create("Alice's risk", owner="Alice")
    reg.create("Bob's risk", owner="Bob")
    alice_risks = reg.list(owner="Alice")
    assert len(alice_risks) == 1
    assert alice_risks[0].owner == "Alice"


def test_filter_combined_status_and_severity(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r1 = reg.create("R1", severity=RiskSeverity.high)
    r2 = reg.create("R2", severity=RiskSeverity.high)
    reg.close(r2.id)
    result = reg.list(status=RiskStatus.open, severity=RiskSeverity.high)
    assert len(result) == 1
    assert result[0].id == r1.id


def test_filter_empty_returns_all(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create("A")
    reg.create("B")
    assert len(reg.list()) == 2


def test_filter_no_match_returns_empty(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create("A", severity=RiskSeverity.low)
    result = reg.list(severity=RiskSeverity.critical)
    assert result == []


def test_filter_by_status_mitigated(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Mitigated risk")
    reg.mitigate(r.id)
    result = reg.list(status=RiskStatus.mitigated)
    assert len(result) == 1


def test_filter_by_status_accepted(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Accepted risk")
    reg.accept(r.id)
    result = reg.list(status=RiskStatus.accepted)
    assert len(result) == 1
    assert result[0].id == r.id


# ---------------------------------------------------------------------------
# Sorting (8 tests)
# ---------------------------------------------------------------------------

def test_sort_by_created_at_desc(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create("First")
    reg.create("Second")
    risks = reg.list(sort_by="created_at", descending=True)
    assert risks[0].title == "Second"


def test_sort_by_created_at_asc(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create("First")
    reg.create("Second")
    risks = reg.list(sort_by="created_at", descending=False)
    assert risks[0].title == "First"


def test_sort_by_severity_descending(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create("L", severity=RiskSeverity.low)
    reg.create("C", severity=RiskSeverity.critical)
    reg.create("M", severity=RiskSeverity.medium)
    risks = reg.list(sort_by="severity", descending=True)
    assert risks[0].severity is RiskSeverity.critical


def test_sort_by_likelihood(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create("L1", likelihood=1)
    reg.create("L5", likelihood=5)
    risks = reg.list(sort_by="likelihood", descending=True)
    assert risks[0].likelihood == 5


def test_sort_by_title(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create("Zebra risk")
    reg.create("Apple risk")
    risks = reg.list(sort_by="title", descending=False)
    assert risks[0].title == "Apple risk"


def test_sort_by_owner(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create("R1", owner="Zara")
    reg.create("R2", owner="Alice")
    risks = reg.list(sort_by="owner", descending=False)
    assert risks[0].owner == "Alice"


def test_sort_default_is_newest_first(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create("Older")
    reg.create("Newer")
    risks = reg.list()
    assert risks[0].title == "Newer"


def test_sort_combined_filter_and_sort(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create("A", owner="Alice", likelihood=2)
    reg.create("B", owner="Alice", likelihood=5)
    reg.create("C", owner="Bob", likelihood=4)
    risks = reg.list(owner="Alice", sort_by="likelihood", descending=True)
    assert risks[0].title == "B"
    assert len(risks) == 2


# ---------------------------------------------------------------------------
# Persistence (8 tests)
# ---------------------------------------------------------------------------

def test_persist_across_sessions(tmp_path: Path) -> None:
    db = tmp_path / "risks.db"
    reg1 = RiskRegistry(db)
    reg1.create("Persisted risk")
    reg1.close()
    reg2 = RiskRegistry(db)
    risks = reg2.list()
    reg2.close()
    assert any(r.title == "Persisted risk" for r in risks)


def test_persist_multiple_risks(tmp_path: Path) -> None:
    db = tmp_path / "risks.db"
    reg1 = RiskRegistry(db)
    for i in range(5):
        reg1.create(f"Risk {i}")
    reg1.close()
    reg2 = RiskRegistry(db)
    assert len(reg2.list()) == 5
    reg2.close()


def test_persist_update_survives_reload(tmp_path: Path) -> None:
    db = tmp_path / "risks.db"
    reg1 = RiskRegistry(db)
    r = reg1.create("Update me")
    reg1.update(r.id, title="Updated title")
    reg1.close()
    reg2 = RiskRegistry(db)
    got = reg2.get(r.id)
    assert got is not None
    assert got.title == "Updated title"
    reg2.close()


def test_persist_delete_survives_reload(tmp_path: Path) -> None:
    db = tmp_path / "risks.db"
    reg1 = RiskRegistry(db)
    r = reg1.create("Delete me")
    reg1.delete(r.id)
    reg1.close()
    reg2 = RiskRegistry(db)
    assert reg2.get(r.id) is None
    reg2.close()


def test_persist_status_change(tmp_path: Path) -> None:
    db = tmp_path / "risks.db"
    reg1 = RiskRegistry(db)
    r = reg1.create("Status risk")
    reg1.close(r.id)
    reg1.close()
    reg2 = RiskRegistry(db)
    got = reg2.get(r.id)
    assert got is not None
    assert got.status is RiskStatus.closed
    reg2.close()


def test_persist_in_memory_isolated() -> None:
    reg1 = _mem()
    reg2 = _mem()
    reg1.create("Only in reg1")
    assert len(reg1.list()) == 1
    assert len(reg2.list()) == 0


def test_persist_concurrent_opens(tmp_path: Path) -> None:
    """Two registry instances on the same file can both read simultaneously."""
    db = tmp_path / "risks.db"
    reg1 = RiskRegistry(db)
    reg1.create("Shared risk")
    reg2 = RiskRegistry(db)
    assert len(reg2.list()) == 1
    reg1.close()
    reg2.close()


def test_persist_empty_on_new_db(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    assert reg.list() == []
    reg.close()


# ---------------------------------------------------------------------------
# Concurrent updates (3 tests)
# ---------------------------------------------------------------------------

def test_concurrent_creates_no_duplication() -> None:
    """Multiple threads creating risks concurrently produce unique ids."""
    reg = _mem()
    results: list[Risk] = []
    lock = threading.Lock()

    def create_risk(title: str) -> None:
        r = reg.create(title)
        with lock:
            results.append(r)

    threads = [threading.Thread(target=create_risk, args=(f"Risk {i}",)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ids = [r.id for r in results]
    assert len(ids) == len(set(ids))  # all unique


def test_concurrent_updates_are_serialised() -> None:
    """Two threads updating the same risk don't corrupt the record."""
    reg = _mem()
    r = reg.create("Shared")
    errors: list[Exception] = []

    def do_update(owner: str) -> None:
        try:
            reg.update(r.id, owner=owner)
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=do_update, args=("Alice",))
    t2 = threading.Thread(target=do_update, args=("Bob",))
    t1.start(); t2.start()
    t1.join(); t2.join()
    assert not errors
    final = reg.get(r.id)
    assert final is not None
    assert final.owner in ("Alice", "Bob")


def test_concurrent_list_and_create() -> None:
    """List can run while another thread is inserting."""
    reg = _mem()
    for i in range(5):
        reg.create(f"Seed {i}")

    errors: list[Exception] = []

    def lister() -> None:
        for _ in range(20):
            try:
                reg.list()
            except Exception as exc:
                errors.append(exc)

    def creator() -> None:
        for i in range(10):
            try:
                reg.create(f"New {i}")
            except Exception as exc:
                errors.append(exc)

    t1 = threading.Thread(target=lister)
    t2 = threading.Thread(target=creator)
    t1.start(); t2.start()
    t1.join(); t2.join()
    assert not errors


# ---------------------------------------------------------------------------
# Confidentiality (3 tests)
# ---------------------------------------------------------------------------

def test_confidential_flag_default_false(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Public risk")
    assert r.confidential is False


def test_confidential_risk_in_list(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Secret risk", confidential=True)
    all_risks = reg.list()
    assert any(risk.id == r.id for risk in all_risks)
    assert any(risk.confidential for risk in all_risks)


def test_export_public_excludes_confidential(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create("Public risk A")
    reg.create("Confidential risk B", confidential=True)
    reg.create("Public risk C")
    public = reg.export_public()
    assert len(public) == 2
    assert all(not r.confidential for r in public)
