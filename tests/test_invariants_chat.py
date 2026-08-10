"""Invariant tests for ChatStore (Phase 2c): session isolation + cascade delete.

Core invariants:
- Messages/actions written to one session are never visible from another
  session, even under a shared connection.
- Deleting a session physically removes its child rows (verified by direct
  ``COUNT(*)`` queries, not just via the public read API) — no orphans.
- The store's RLock prevents interleaved writes from corrupting state under
  concurrent access.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from hermes_assistant.chat.model import ChatRole
from hermes_assistant.chat.store import ChatStore


@pytest.fixture
def store(tmp_path: Path) -> ChatStore:
    s = ChatStore(tmp_path / "chat.db")
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Session isolation
# ---------------------------------------------------------------------------


def test_messages_never_leak_between_sessions(store: ChatStore) -> None:
    session_a = store.create_session("proj-1")
    session_b = store.create_session("proj-1")

    store.add_message(session_a.id, ChatRole.user, "secret to A")
    store.add_message(session_b.id, ChatRole.user, "secret to B")

    msgs_a = store.list_messages(session_a.id)
    msgs_b = store.list_messages(session_b.id)

    assert [m.content for m in msgs_a] == ["secret to A"]
    assert [m.content for m in msgs_b] == ["secret to B"]
    assert "secret to B" not in [m.content for m in msgs_a]
    assert "secret to A" not in [m.content for m in msgs_b]


def test_actions_never_leak_between_sessions(store: ChatStore) -> None:
    session_a = store.create_session("proj-1")
    session_b = store.create_session("proj-1")
    msg_a = store.add_message(session_a.id, ChatRole.user, "create risk A")
    msg_b = store.add_message(session_b.id, ChatRole.user, "create risk B")

    store.add_action(session_a.id, msg_a.id, "create_risk", params={"title": "A"})
    store.add_action(session_b.id, msg_b.id, "create_risk", params={"title": "B"})

    actions_a = store.list_actions(session_a.id)
    actions_b = store.list_actions(session_b.id)
    assert [a.params["title"] for a in actions_a] == ["A"]
    assert [a.params["title"] for a in actions_b] == ["B"]


def test_cross_project_sessions_isolated_via_list_sessions(store: ChatStore) -> None:
    store.create_session("proj-a")
    store.create_session("proj-b")
    assert {s.project_id for s in store.list_sessions("proj-a")} == {"proj-a"}
    assert {s.project_id for s in store.list_sessions("proj-b")} == {"proj-b"}


# ---------------------------------------------------------------------------
# FK cascade on delete — verified via direct row counts
# ---------------------------------------------------------------------------


def test_delete_session_removes_message_rows_physically(store: ChatStore) -> None:
    session = store.create_session("proj-1")
    for i in range(5):
        store.add_message(session.id, ChatRole.user, f"msg {i}")

    before = store._conn.execute(
        "SELECT COUNT(*) FROM chat_messages WHERE session_id = ?", (session.id,)
    ).fetchone()[0]
    assert before == 5

    store.delete_session(session.id)

    after = store._conn.execute(
        "SELECT COUNT(*) FROM chat_messages WHERE session_id = ?", (session.id,)
    ).fetchone()[0]
    assert after == 0


def test_delete_session_removes_action_rows_physically(store: ChatStore) -> None:
    session = store.create_session("proj-1")
    msg = store.add_message(session.id, ChatRole.user, "create a risk")
    store.add_action(session.id, msg.id, "create_risk")

    before = store._conn.execute(
        "SELECT COUNT(*) FROM chat_actions WHERE session_id = ?", (session.id,)
    ).fetchone()[0]
    assert before == 1

    store.delete_session(session.id)

    after = store._conn.execute(
        "SELECT COUNT(*) FROM chat_actions WHERE session_id = ?", (session.id,)
    ).fetchone()[0]
    assert after == 0


def test_delete_one_session_does_not_cascade_into_sibling(store: ChatStore) -> None:
    session_a = store.create_session("proj-1")
    session_b = store.create_session("proj-1")
    store.add_message(session_a.id, ChatRole.user, "a")
    store.add_message(session_b.id, ChatRole.user, "b")

    store.delete_session(session_a.id)

    assert store.get_session(session_b.id) is not None
    assert [m.content for m in store.list_messages(session_b.id)] == ["b"]


def test_no_orphaned_rows_after_bulk_delete(store: ChatStore) -> None:
    ids = []
    for i in range(10):
        s = store.create_session("proj-bulk")
        m = store.add_message(s.id, ChatRole.user, f"msg-{i}")
        store.add_action(s.id, m.id, "smalltalk")
        ids.append(s.id)

    for sid in ids:
        store.delete_session(sid)

    assert store._conn.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0] == 0
    assert store._conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 0
    assert store._conn.execute("SELECT COUNT(*) FROM chat_actions").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# RLock prevents concurrent corruption
# ---------------------------------------------------------------------------


def test_concurrent_message_writes_no_data_loss(store: ChatStore) -> None:
    session = store.create_session("proj-concurrent")
    errors: list[Exception] = []

    def _write(i: int) -> None:
        try:
            store.add_message(session.id, ChatRole.user, f"concurrent-{i}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_write, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert errors == []
    msgs = store.list_messages(session.id)
    assert len(msgs) == 20
    assert {m.content for m in msgs} == {f"concurrent-{i}" for i in range(20)}


def test_concurrent_session_creation_all_succeed(store: ChatStore) -> None:
    created: list[str] = []
    lock = threading.Lock()

    def _create() -> None:
        s = store.create_session("proj-race")
        with lock:
            created.append(s.id)

    threads = [threading.Thread(target=_create) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(created) == 20
    assert len(set(created)) == 20  # every session id is unique — no collisions
    assert len(store.list_sessions("proj-race")) == 20
