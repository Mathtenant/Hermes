"""P0 edge-case simulations: correctness gaps under concurrency (S1-S3).

S1 is a genuine pass/fail test of the WAL + busy_timeout + RLock concurrency
model already in place and is expected to PASS.

S2 and S3 are marked ``xfail``: they encode the invariant we *want* to hold
(no cross-connection plan-version collision; closed risks stay closed on
re-import) and currently fail because neither guarantee is implemented yet.
They are deliberately not weakened — the assertions are the desired
behaviour, not the observed one — and are left as a canary: if a future
change adds cross-connection locking or import-time lifecycle enforcement,
these tests will start passing (XPASS) and should be un-xfailed.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from hermes_assistant.plans.editor import PlanEditor
from hermes_assistant.plans.model import PlanItem
from hermes_assistant.risks.model import RiskStatus
from hermes_assistant.risks.registry import RiskRegistry
from hermes_assistant.webapp.import_json import import_payload

from .faults import run_barrier_synced, run_concurrent
from .snapshots import assert_invariants

XFAIL_REASON = "Pending D-decision on atomicity/resurrection"


# --------------------------------------------------------------------------- #
# S1 — cross-connection import-vs-live race
# --------------------------------------------------------------------------- #


def test_s1_cross_connection_import_vs_live_race(tmp_path: Path) -> None:
    """A live RiskRegistry connection and a separate import-triggered
    RiskRegistry connection hammer the same risks.db file at the same instant
    (barrier-synchronised): 200 live creates on connection A racing 1000
    imported creates on connection B (created fresh by ``import_payload``).

    Expected: WAL + busy_timeout + per-instance RLock is sufficient to
    serialise the two connections at the SQLite level — no errors, no lost
    rows, no torn state.
    """
    db_path = tmp_path / "risks.db"
    live_reg = RiskRegistry(db_path)

    def do_live() -> list[BaseException]:
        def _one(i: int) -> None:
            live_reg.create(f"live-{i}")

        outcomes = run_concurrent(_one, 200, max_workers=16, timeout=60)
        return [exc for _, exc in outcomes if exc is not None]

    def do_import():
        payload = {
            "risks": [
                {"id": f"import-{i}", "title": f"import risk {i}"} for i in range(1000)
            ]
        }
        return import_payload(payload, risks_db=str(db_path))

    (live_errors, live_exc), (import_result, import_exc) = run_barrier_synced(
        [do_live, do_import], timeout=60
    )

    assert live_exc is None, f"do_live thread raised: {live_exc!r}"
    assert import_exc is None, f"do_import thread raised: {import_exc!r}"
    assert live_errors == [], f"live writer errors: {live_errors}"
    assert import_result.created == 1000
    assert import_result.ok

    final = live_reg.list()
    assert len(final) == 1200, f"expected 1200 rows, got {len(final)}"
    assert_invariants(live_reg)
    live_reg.close_connection()


# --------------------------------------------------------------------------- #
# S2 — plan version collision (cross-connection)
# --------------------------------------------------------------------------- #


@pytest.mark.xfail(reason=XFAIL_REASON, strict=False)
def test_s2_plan_version_collision_two_connections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two independent ``PlanEditor`` connections both update the same plan.

    ``PlanEditor._next_version`` reads ``MAX(version)`` and adds 1; this is
    correct *within* one instance (serialised by its own RLock) but is not
    coordinated *across* instances/processes at all. We force the narrow
    race window open with a barrier + injected pause between "compute next
    version" and "insert it", so both connections deterministically compute
    the same next version number and race to insert it — one must lose with
    a PK collision (``sqlite3.IntegrityError``).

    We assert the invariant we actually want (no error, no collision); this
    currently fails, exposing the missing cross-connection concurrency
    control for plan versioning.
    """
    db_path = tmp_path / "plans.db"
    editor_a = PlanEditor(db_path)
    editor_a.create("plan-race", [PlanItem(title="seed")])
    editor_b = PlanEditor(db_path)

    orig_next_version = PlanEditor._next_version
    barrier = threading.Barrier(2, timeout=10)

    def _slow_next_version(self: PlanEditor, plan_id: str) -> int:
        v = orig_next_version(self, plan_id)
        barrier.wait()
        time.sleep(0.1)  # widen the race window past the point of no return
        return v

    monkeypatch.setattr(PlanEditor, "_next_version", _slow_next_version)

    errors: list[BaseException] = []
    lock = threading.Lock()

    def _update(editor: PlanEditor, i: int) -> None:
        try:
            editor.update("plan-race", [PlanItem(title=f"item-{i}")])
        except Exception as exc:  # noqa: BLE001 - collected for assertion
            with lock:
                errors.append(exc)

    t1 = threading.Thread(target=_update, args=(editor_a, 1))
    t2 = threading.Thread(target=_update, args=(editor_b, 2))
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)

    assert errors == [], f"cross-connection version collision: {errors}"

    editor_a.close()
    editor_b.close()


@pytest.mark.xfail(reason=XFAIL_REASON, strict=False)
def test_s2_batched_plan_import_collides_with_live_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A batched plan import racing a live update on the *same* plan_id.

    ``import_payload`` opens its own ``PlanEditor`` for the duration of the
    import; if that races a live connection's ``update()`` on the same plan,
    the same unguarded ``_next_version`` gap applies to the import path too.
    """
    db_path = tmp_path / "plans.db"
    live_editor = PlanEditor(db_path)
    live_editor.create("plan-shared", [PlanItem(title="seed")])

    orig_next_version = PlanEditor._next_version
    barrier = threading.Barrier(2, timeout=10)

    def _slow_next_version(self: PlanEditor, plan_id: str) -> int:
        v = orig_next_version(self, plan_id)
        barrier.wait()
        time.sleep(0.1)
        return v

    monkeypatch.setattr(PlanEditor, "_next_version", _slow_next_version)

    errors: list[BaseException] = []

    def do_live() -> None:
        try:
            live_editor.update("plan-shared", [PlanItem(title="live-update")])
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    def do_import() -> None:
        try:
            payload = {
                "plans": [
                    {
                        "plan_id": "plan-shared",
                        "items": [{"title": "imported-update"}],
                    }
                ]
            }
            result = import_payload(payload, plans_db=str(db_path))
            if result.errors:
                errors.append(RuntimeError("; ".join(result.errors)))
        except Exception as exc:  # noqa: BLE001 - collected for assertion
            errors.append(exc)

    t1 = threading.Thread(target=do_live)
    t2 = threading.Thread(target=do_import)
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)

    assert errors == [], f"import-vs-live version collision: {errors}"
    live_editor.close()


# --------------------------------------------------------------------------- #
# S3 — closed-risk resurrection via re-import
# --------------------------------------------------------------------------- #


@pytest.mark.xfail(reason=XFAIL_REASON, strict=False)
def test_s3_closed_risk_resurrection_via_reimport(tmp_path: Path) -> None:
    """A closed risk re-imported with ``status: "open"`` must stay closed.

    ``RiskRegistry.update()`` enforces ``_LEGAL_TRANSITIONS`` (closed is
    terminal), but ``_import_risks``'s pass-2 write path bypasses the store's
    public API entirely and does a raw ``INSERT OR REPLACE`` — so the D5
    lifecycle policy ("closed cannot be resurrected; create a new risk
    instead") is not enforced on the import path. This test asserts the
    policy should hold end-to-end (including via import) and currently fails.
    """
    db_path = tmp_path / "risks.db"
    reg = RiskRegistry(db_path)
    risk = reg.create("Budget overrun", external_ref="ext-1")
    reg.close(risk.id)
    closed = reg.get(risk.id)
    assert closed is not None
    assert closed.status is RiskStatus.closed

    payload = {
        "risks": [
            {"external_ref": "ext-1", "title": "Budget overrun", "status": "open"}
        ]
    }
    result = import_payload(payload, risks_db=str(db_path))
    assert result.updated == 1

    resurrected = reg.get(risk.id)
    assert resurrected is not None
    assert resurrected.status is RiskStatus.closed, (
        "D5 policy violated: closed risk was resurrected to "
        f"{resurrected.status.value!r} via re-import"
    )
    reg.close_connection()
