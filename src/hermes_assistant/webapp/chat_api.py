"""FastAPI chat endpoints (Phase 5.5).

Exposes the chat assistant over HTTP: send a message, list/get/delete
sessions. All blocking work (SQLite, LLM) runs in a worker thread via
``run_in_threadpool`` so the event loop stays responsive. Every dict response
passes through :func:`confidentiality_guard` before delivery.

The :class:`ChatService` is built lazily as a process-wide singleton and reads
its database paths from :mod:`hermes_assistant.config.settings` at first use,
so tests can point it at temp databases by resetting ``_chat_service`` after
patching ``settings``.
"""

from __future__ import annotations

import functools
import json as _json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from hermes_assistant.chat.executor import ActionExecutor
from hermes_assistant.chat.router import IntentRouter
from hermes_assistant.chat.service import ChatService, ConfidentialityGuardError
from hermes_assistant.chat.store import ChatStore
from hermes_assistant.config import settings
from hermes_assistant.llm.client import OllamaClient
from hermes_assistant.plans.editor import PlanEditor
from hermes_assistant.risks.registry import RiskRegistry
from hermes_assistant.tasks.store import TaskStore


import logging as _logging

_log = _logging.getLogger(__name__)


def confidentiality_guard(func):  # type: ignore[no-untyped-def]
    """Validate dict responses for confidential data before delivery.

    Mirrors ``webapp.server.confidentiality_guard`` but imports the shared
    validator lazily at request time. This avoids a module-load import cycle:
    ``server`` mounts this router at import, so this module must not import
    ``server`` at the top level.

    H2: violation details are logged server-side only; the client receives a
    generic "Internal error" message so forbidden field names are not disclosed.
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
        response = await func(*args, **kwargs)
        if isinstance(response, dict):
            from hermes_assistant.webapp.server import (
                _redact_user_authored,
                _validate_safe_json,
            )

            # H1: exclude user-authored message content (their own email/path)
            # from the PII scan so GET /api/chat/sessions/{id} does not 500 on
            # a message the user themselves typed.
            violations = _validate_safe_json(
                _json.dumps(response),
                _json.dumps(_redact_user_authored(response)),
            )
            if violations:
                # H2: log detail server-side; return generic message to client.
                _log.warning(
                    "Confidentiality guard triggered on %s: %s",
                    func.__name__,
                    "; ".join(violations),
                )
                raise HTTPException(status_code=500, detail="Internal error")
        return response

    return wrapper


router = APIRouter(prefix="/api/chat", tags=["chat"])

MAX_MESSAGE_CHARS = 2000

# Process-wide singleton. Reset to None (after patching settings) to rebuild
# the service against fresh database paths — used by the test suite.
_chat_service: ChatService | None = None


def get_chat_service() -> ChatService:
    """Build (once) and return the shared :class:`ChatService`.

    Database paths are derived from ``settings`` at first call, mirroring the
    convention in :func:`hermes_assistant.webapp.server._get_import_paths`.
    """
    global _chat_service
    if _chat_service is None:
        data_dir = Path(settings.data_dir)
        store = ChatStore(settings.chat_db_path)
        client = OllamaClient()
        intent_router = IntentRouter(client)
        risk_registry = RiskRegistry(data_dir / "risks.db")
        task_store = TaskStore(settings.tasks_db_path)
        plan_editor = PlanEditor(data_dir / "plans.db")
        executor = ActionExecutor(risk_registry, task_store, plan_editor)
        _chat_service = ChatService(store, intent_router, executor, client)
    return _chat_service


class ChatMessageRequest(BaseModel):
    """Body for ``POST /api/chat/message``."""

    message: str
    project_id: str
    session_id: str | None = None


class ChatMessageResponse(BaseModel):
    """Response for ``POST /api/chat/message``."""

    session_id: str
    message: dict
    action: dict | None = None
    suggestions: list[str] = []


@router.post("/message")
async def send_message(req: ChatMessageRequest) -> dict:
    """Send a message and return the assistant's response.

    The confidentiality guard now runs inside ``ChatService.handle_turn``
    *before* the assistant message is persisted (H1 fix). The ``@confidentiality_guard``
    decorator is therefore not needed on this endpoint.
    """
    message = (req.message or "").strip()
    if not message or len(req.message) > MAX_MESSAGE_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"Message must be 1-{MAX_MESSAGE_CHARS} chars",
        )
    if not req.project_id:
        raise HTTPException(status_code=422, detail="project_id required")

    service = get_chat_service()

    def handle():  # noqa: ANN202
        return service.handle_turn(req.message, req.project_id, req.session_id)

    try:
        turn = await run_in_threadpool(handle)
    except ConfidentialityGuardError:
        # Guard already logged the details in service.handle_turn; surface generic error.
        raise HTTPException(status_code=500, detail="Internal error")
    return ChatMessageResponse(
        session_id=turn.session_id,
        message=turn.message.model_dump(),
        action=turn.action.model_dump() if turn.action else None,
        suggestions=turn.suggestions,
    ).model_dump()


@router.get("/sessions")
@confidentiality_guard
async def list_sessions(project_id: str | None = Query(default=None)) -> dict:
    """List chat sessions, optionally filtered by project."""
    service = get_chat_service()

    def handle():  # noqa: ANN202
        return service.store.list_sessions(project_id)

    sessions = await run_in_threadpool(handle)
    return {"sessions": [s.model_dump() for s in sessions]}


@router.get("/sessions/{session_id}")
@confidentiality_guard
async def get_session(session_id: str) -> dict:
    """Return a session together with its full message history."""
    service = get_chat_service()

    def handle():  # noqa: ANN202
        session = service.store.get_session(session_id)
        if session is None:
            return None
        messages = service.store.list_messages(session_id)
        return {"session": session, "messages": messages}

    result = await run_in_threadpool(handle)
    if result is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session": result["session"].model_dump(),
        "messages": [m.model_dump() for m in result["messages"]],
    }


@router.delete("/sessions/{session_id}")
@confidentiality_guard
async def delete_session(session_id: str) -> dict:
    """Delete a session (cascade-deletes its messages and actions)."""
    service = get_chat_service()

    def handle():  # noqa: ANN202
        return service.store.delete_session(session_id)

    deleted = await run_in_threadpool(handle)
    return {"deleted": deleted}
