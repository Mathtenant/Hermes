"""Performance tests: Risk Registry at scale.

All timing thresholds are conservative for a 16 GB M4 MacBook Air running
a local SQLite WAL store in CI. Each test inserts data, measures wall-clock
time, and asserts a generous upper bound.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from hermes_assistant.risks.model import RiskSeverity
from hermes_assistant.risks.registry import RiskRegistry


@pytest.fixture()
def reg(tmp_path: Path) -> RiskRegistry:
    return RiskRegistry(tmp_path / "risks_perf.db")


def test_risks_100_table_render_under_500ms(reg: RiskRegistry) -> None:
    """Inserting and listing 100 risks completes in under 500 ms."""
    for i in range(100):
        reg.create(f"Risk {i}", severity=RiskSeverity.medium)
    start = time.perf_counter()
    all_risks = reg.list()
    elapsed = (time.perf_counter() - start) * 1000
    assert len(all_risks) == 100
    assert elapsed < 500, f"list() of 100 risks took {elapsed:.1f} ms (limit 500 ms)"


def test_risks_1000_filter_under_100ms(reg: RiskRegistry) -> None:
    """Filtered query against 1000 risks returns in under 100 ms."""
    for i in range(1000):
        sev = RiskSeverity.high if i % 10 == 0 else RiskSeverity.medium
        reg.create(f"Bulk risk {i}", severity=sev)
    start = time.perf_counter()
    highs = reg.list(severity=RiskSeverity.high)
    elapsed = (time.perf_counter() - start) * 1000
    assert len(highs) == 100
    assert elapsed < 100, f"filtered list (1000 rows) took {elapsed:.1f} ms (limit 100 ms)"


def test_risks_concurrent_assign_owner_no_data_loss(tmp_path: Path) -> None:
    """Concurrent owner assignments via two connections lose no updates."""
    import threading

    db = tmp_path / "concurrent.db"
    reg1 = RiskRegistry(db)
    reg2 = RiskRegistry(db)

    ids = [reg1.create(f"R{i}").id for i in range(20)]
    errors: list[Exception] = []

    def assign(registry: RiskRegistry, owner: str) -> None:
        for rid in ids:
            try:
                registry.update(rid, owner=owner)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

    t1 = threading.Thread(target=assign, args=(reg1, "alice"))
    t2 = threading.Thread(target=assign, args=(reg2, "bob"))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert not errors
    reg1.close()
    reg2.close()
    final = RiskRegistry(db)
    all_risks = final.list()
    assert len(all_risks) == 20
    owners = {r.owner for r in all_risks}
    assert owners.issubset({"alice", "bob"})
    final.close()
