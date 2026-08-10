"""Invariant tests for RiskRegistry (Phase 2b): lifecycle + confidentiality gaps.

Covers the risk status state machine (legal transitions, and the illegal-
transition guard that Phase 2f/model-fix adds), the ``export_public``
confidentiality boundary, and concurrent-write safety of ``update``.

``test_illegal_transition_closed_to_open_raises`` and
``test_accept_sets_accepted_at`` originally shipped as ``xfail(strict=True)``
pending the Phase 2f model fix (``src/hermes_assistant/risks/model.py`` +
``registry.py`` — added ``Risk.accepted_at`` and the ``_LEGAL_TRANSITIONS``
guard in ``RiskRegistry.update``). The fix has landed, so both now assert the
guard directly as regular passing tests.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from hermes_assistant.risks.model import RiskStatus
from hermes_assistant.risks.registry import RiskRegistry


def _reg(tmp_path: Path) -> RiskRegistry:
    return RiskRegistry(tmp_path / "risks.db")


# ---------------------------------------------------------------------------
# Legal transitions
# ---------------------------------------------------------------------------


def test_open_to_mitigated(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Vendor delay")
    assert r.status is RiskStatus.open
    updated = reg.mitigate(r.id)
    assert updated.status is RiskStatus.mitigated
    reg.close_connection()


def test_mitigated_to_accepted(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Vendor delay")
    reg.mitigate(r.id)
    updated = reg.accept(r.id)
    assert updated.status is RiskStatus.accepted
    reg.close_connection()


def test_accepted_to_closed(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Vendor delay")
    reg.mitigate(r.id)
    reg.accept(r.id)
    updated = reg.close(r.id)
    assert updated is not None
    assert updated.status is RiskStatus.closed
    reg.close_connection()


def test_open_directly_to_accepted_is_legal(tmp_path: Path) -> None:
    """A risk owner may accept residual risk without a mitigation step."""
    reg = _reg(tmp_path)
    r = reg.create("Key person risk")
    updated = reg.accept(r.id)
    assert updated.status is RiskStatus.accepted
    reg.close_connection()


def test_open_directly_to_closed_is_legal(tmp_path: Path) -> None:
    """A risk that turns out not to apply can be closed straight from open."""
    reg = _reg(tmp_path)
    r = reg.create("Non-issue")
    updated = reg.close(r.id)
    assert updated is not None
    assert updated.status is RiskStatus.closed
    reg.close_connection()


# ---------------------------------------------------------------------------
# Illegal transition guard (Phase 2f model fix — now landed)
# ---------------------------------------------------------------------------


def test_illegal_transition_closed_to_open_raises(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Resolved issue")
    reg.close(r.id)
    with pytest.raises(ValueError):
        reg.update(r.id, status=RiskStatus.open)
    reg.close_connection()


def test_illegal_transition_closed_to_mitigated_raises(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Resolved issue")
    reg.close(r.id)
    with pytest.raises(ValueError):
        reg.mitigate(r.id)
    reg.close_connection()


def test_closed_risk_stays_closed_after_failed_transition(tmp_path: Path) -> None:
    """A rejected transition must not leave the row in a half-updated state."""
    reg = _reg(tmp_path)
    r = reg.create("Resolved issue")
    reg.close(r.id)
    with pytest.raises(ValueError):
        reg.update(r.id, status=RiskStatus.open)
    assert reg.get(r.id).status is RiskStatus.closed  # type: ignore[union-attr]
    reg.close_connection()


def test_accept_sets_accepted_at(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Deferred risk")
    assert r.accepted_at is None
    updated = reg.accept(r.id)
    assert updated.accepted_at is not None
    reg.close_connection()


def test_accepted_at_persists_across_reload(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Deferred risk")
    reg.accept(r.id)
    reloaded = reg.get(r.id)
    assert reloaded is not None
    assert reloaded.accepted_at is not None
    reg.close_connection()


# ---------------------------------------------------------------------------
# Confidentiality boundary — export_public()
# ---------------------------------------------------------------------------


def test_export_public_omits_confidential_risks(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create("Public risk", confidential=False)
    reg.create("Secret risk", confidential=True)

    public = reg.export_public()
    titles = {r.title for r in public}
    assert "Public risk" in titles
    assert "Secret risk" not in titles
    reg.close_connection()


def test_export_public_all_confidential_returns_empty(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create("Secret one", confidential=True)
    reg.create("Secret two", confidential=True)

    assert reg.export_public() == []
    reg.close_connection()


def test_export_public_returned_risks_have_no_confidential_flag_leak(tmp_path: Path) -> None:
    """Every item returned by export_public must itself be non-confidential —
    guards against a future regression that forgets the WHERE clause."""
    reg = _reg(tmp_path)
    reg.create("Public risk", confidential=False)
    reg.create("Secret risk", confidential=True)

    for risk in reg.export_public():
        assert risk.confidential is False
    reg.close_connection()


# ---------------------------------------------------------------------------
# Concurrent writes
# ---------------------------------------------------------------------------


def test_concurrent_owner_assignment_no_data_loss(tmp_path: Path) -> None:
    """20 threads racing to assign an owner must leave the registry in a
    single, consistent final state — no crashes, no partial writes."""
    reg = _reg(tmp_path)
    r = reg.create("Shared risk")

    errors: list[Exception] = []

    def _assign(owner: str) -> None:
        try:
            reg.update(r.id, owner=owner)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_assign, args=(f"owner-{i}",)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert errors == []
    final = reg.get(r.id)
    assert final is not None
    assert final.owner.startswith("owner-")
    reg.close_connection()


def test_concurrent_status_updates_leave_registry_consistent(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    r = reg.create("Contended risk")

    def _mitigate() -> None:
        reg.mitigate(r.id)

    threads = [threading.Thread(target=_mitigate) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    final = reg.get(r.id)
    assert final is not None
    assert final.status is RiskStatus.mitigated
    reg.close_connection()
