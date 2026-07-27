"""Unit tests for the chat SQLite store (in-memory, no network)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_assistant.chat.model import ChatRole
from hermes_assistant.chat.store import ChatStore


@pytest.fixture
def store() -> ChatStore:
    """An isolated in-memory chat store per test."""
    s = ChatStore(":memory:")
    yield s
    s.close()


# -- sessions ---------------------------------------------------------- #
def test_create_session_sets_fields(store: ChatStore) -> None:
    session = store.create_session("proj-1", title="Kickoff")
    assert session.id  # auto-generated, non-empty
    assert session.project_id == "proj-1"
    assert session.title == "Kickoff"
    assert session.created_at
    assert session.updated_at == session.created_at


def test_get_session_roundtrip_and_missing(store: ChatStore) -> None:
    session = store.create_session("proj-1")
    fetched = store.get_session(session.id)
    assert fetched is not None
    assert fetched.id == session.id
    assert store.get_session("does-not-exist") is None


def test_list_sessions_filters_by_project(store: ChatStore) -> None:
    a = store.create_session("proj-a")
    b = store.create_session("proj-b")
    store.create_session("proj-a")

    proj_a = store.list_sessions("proj-a")
    assert len(proj_a) == 2
    assert {s.project_id for s in proj_a} == {"proj-a"}

    proj_b = store.list_sessions("proj-b")
    assert [s.id for s in proj_b] == [b.id]

    assert len(store.list_sessions()) == 3
    assert a.id in {s.id for s in store.list_sessions()}


def test_touch_session_updates_timestamp(store: ChatStore) -> None:
    session = store.create_session("proj-1")
    store._conn.execute(
        "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
        ("2000-01-01T00:00:00+00:00", session.id),
    )
    store._conn.commit()
    store.touch_session(session.id)
    refreshed = store.get_session(session.id)
    assert refreshed is not None
    assert refreshed.updated_at > "2000-01-01T00:00:00+00:00"


# -- messages ---------------------------------------------------------- #
def test_add_message_stores_fields(store: ChatStore) -> None:
    session = store.create_session("proj-1")
    msg = store.add_message(
        session.id,
        ChatRole.user,
        "hello there",
        metadata={"lang": "en", "tokens": "3"},
    )
    assert msg.id
    assert msg.session_id == session.id
    assert msg.role == ChatRole.user
    assert msg.content == "hello there"
    assert msg.metadata == {"lang": "en", "tokens": "3"}
    assert msg.created_at


def test_list_messages_sorted_and_empty(store: ChatStore) -> None:
    session = store.create_session("proj-1")
    assert store.list_messages(session.id) == []

    store.add_message(session.id, ChatRole.user, "first")
    store.add_message(session.id, ChatRole.assistant, "second")
    store.add_message(session.id, ChatRole.user, "third")

    msgs = store.list_messages(session.id)
    assert [m.content for m in msgs] == ["first", "second", "third"]
    assert msgs == sorted(msgs, key=lambda m: (m.created_at, m.id))


def test_add_message_large_content(store: ChatStore) -> None:
    session = store.create_session("proj-1")
    big = "x" * 2000
    msg = store.add_message(session.id, ChatRole.assistant, big)
    fetched = store.list_messages(session.id)[0]
    assert fetched.content == big
    assert len(fetched.content) == 2000
    assert msg.content == big


def test_add_message_touches_session(store: ChatStore) -> None:
    session = store.create_session("proj-1")
    store._conn.execute(
        "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
        ("2000-01-01T00:00:00+00:00", session.id),
    )
    store._conn.commit()
    store.add_message(session.id, ChatRole.user, "ping")
    refreshed = store.get_session(session.id)
    assert refreshed is not None
    assert refreshed.updated_at > "2000-01-01T00:00:00+00:00"


# -- actions ----------------------------------------------------------- #
def test_add_action_stores_fields(store: ChatStore) -> None:
    session = store.create_session("proj-1")
    msg = store.add_message(session.id, ChatRole.user, "create a risk")
    action = store.add_action(
        session.id,
        msg.id,
        "create_risk",
        params={"title": "Budget overrun"},
        result={"risk_id": "R-1"},
    )
    assert action.id
    assert action.session_id == session.id
    assert action.message_id == msg.id
    assert action.action_type == "create_risk"
    assert action.params == {"title": "Budget overrun"}
    assert action.result == {"risk_id": "R-1"}
    assert action.executed_at


# -- cascade & integrity ---------------------------------------------- #
def test_delete_session_cascades(store: ChatStore) -> None:
    session = store.create_session("proj-1")
    msg = store.add_message(session.id, ChatRole.user, "hi")
    store.add_action(session.id, msg.id, "smalltalk")

    assert store.delete_session(session.id) is True
    assert store.get_session(session.id) is None
    assert store.list_messages(session.id) == []
    assert store.list_actions(session.id) == []
    # No orphaned rows anywhere.
    assert store._conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 0
    assert store._conn.execute("SELECT COUNT(*) FROM chat_actions").fetchone()[0] == 0


def test_delete_missing_session_returns_false(store: ChatStore) -> None:
    assert store.delete_session("nope") is False


def test_foreign_key_constraint_enforced(store: ChatStore) -> None:
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        store.add_message("ghost-session", ChatRole.user, "orphan")


# -- isolation & persistence ------------------------------------------ #
def test_memory_isolation_between_stores(tmp_path: Path) -> None:
    a = ChatStore(":memory:")
    b = ChatStore(":memory:")
    a.create_session("proj-1")
    assert len(a.list_sessions()) == 1
    assert b.list_sessions() == []  # separate in-memory DBs
    a.close()
    b.close()

    # File-backed store persists across reopen.
    db = tmp_path / "chat.db"
    s1 = ChatStore(db)
    sess = s1.create_session("proj-x")
    s1.add_message(sess.id, ChatRole.user, "persist me")
    s1.close()

    s2 = ChatStore(db)
    assert len(s2.list_sessions("proj-x")) == 1
    assert [m.content for m in s2.list_messages(sess.id)] == ["persist me"]
    s2.close()
