"""Chat assistant: data models and SQLite-backed persistence.

Phase 5.1 provides the storage foundation — sessions, messages, and actions —
that the higher chat orchestration layers build on.
"""

from .model import (
    AssistantTurn,
    ChatAction,
    ChatContext,
    ChatMessage,
    ChatRole,
    ChatSession,
    IntentClassification,
)
from .store import ChatStore

__all__ = [
    "ChatRole",
    "ChatMessage",
    "ChatSession",
    "ChatAction",
    "IntentClassification",
    "ChatContext",
    "AssistantTurn",
    "ChatStore",
]
