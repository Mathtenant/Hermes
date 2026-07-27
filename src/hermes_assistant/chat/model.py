"""Pydantic models for the chat assistant.

These types describe the persisted chat surface (sessions, messages, actions)
plus the transient reasoning artifacts (intent classification, context bundle,
assistant turn) that the chat orchestrator passes around. Persisted models use
string ISO timestamps to mirror the SQLite storage format used elsewhere in the
project (see ``jobqueue.jobs``).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatRole(str, Enum):
    """Who authored a chat message."""

    user = "user"
    assistant = "assistant"


class ChatMessage(BaseModel):
    """A single message in a chat session."""

    id: str
    session_id: str
    role: ChatRole
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class ChatSession(BaseModel):
    """A conversation scoped to a single project."""

    id: str
    project_id: str
    title: str | None = None
    created_at: str
    updated_at: str


class ChatAction(BaseModel):
    """A side-effecting action taken in response to a message."""

    id: str
    session_id: str
    message_id: str
    action_type: str
    params: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    executed_at: str


class IntentClassification(BaseModel):
    """The classified intent of a user message plus extracted params."""

    intent: Literal[
        "create_risk",
        "create_task",
        "list_risks",
        "show_plan",
        "review_status",
        "run_review",
        "answer_question",
        "smalltalk",
    ]
    params: dict[str, str] = Field(default_factory=dict)
    confidence: float


class ChatContext(BaseModel):
    """Project state assembled for grounding an assistant reply."""

    project_id: str
    risks: list[dict] = Field(default_factory=list)
    plan_summary: str | None = None
    open_task_count: int = 0
    latest_verdict: str | None = None


class AssistantTurn(BaseModel):
    """The full result of one assistant turn: message, optional action, hints."""

    session_id: str
    message: ChatMessage
    action: ChatAction | None = None
    suggestions: list[str] = Field(default_factory=list)
