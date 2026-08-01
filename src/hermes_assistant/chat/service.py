"""Chat orchestration service (Phase 5.4).

``ChatService.handle_turn`` runs one full assistant turn end to end:

1. Load or create the session.
2. Persist the user message.
3. Assemble a :class:`ChatContext` from project state.
4. Classify intent (ROUTER model).
5. Execute the action (high confidence, non-smalltalk) or fall back to a
   grounded answer.
6. Format a natural-language reply.
7. Persist the assistant message and (if applicable) the action.
8. Touch the session and compute follow-up suggestions.

Intent classification is defensively wrapped: if the router raises (LLM
unavailable, model not pulled, transport error), the turn degrades to a safe
``answer_question`` fallback instead of failing the request.
"""

from __future__ import annotations

import json as _json
import logging
from typing import Any

from .executor import ActionExecutor
from .model import (
    AssistantTurn,
    ChatContext,
    ChatRole,
    IntentClassification,
)
from .router import IntentRouter
from .store import ChatStore

logger = logging.getLogger(__name__)

_CONFIDENCE_THRESHOLD = 0.7


class ConfidentialityGuardError(Exception):
    """Raised when the confidentiality guard blocks an assistant response.

    No violation details are included here — callers must log at the
    point of detection (in handle_turn) and surface only a generic
    message to the client.
    """


class ResponseFormatter:
    """Render an executor result dict into a natural-language reply.

    Conversational intents (``smalltalk``, ``capability``, ``meta``,
    ``unknown``) are answered from a static, language-aware YAML template
    (``responses.yaml``) with no LLM call. All other intents fall through to
    :meth:`format_result_existing`, which renders an executor result dict.
    """

    _RESPONSES: dict[str, Any] | None = None
    _CONVERSATIONAL = ("smalltalk", "capability", "meta", "unknown")

    @classmethod
    def load_responses(cls) -> dict[str, Any]:
        """Lazily load and cache the static response templates."""
        if cls._RESPONSES is None:
            import yaml
            from pathlib import Path

            responses_path = Path(__file__).parent / "responses.yaml"
            cls._RESPONSES = yaml.safe_load(responses_path.read_text())
        return cls._RESPONSES

    @staticmethod
    def detect_language(message: str) -> str:
        """Detect DE/EN from message content (umlauts/ß imply German)."""
        return "de" if any(c in message for c in "äöüßÄÖÜ") else "en"

    @classmethod
    def format_result(
        cls, result: dict[str, Any], intent: str, message: str = ""
    ) -> str:
        """Convert an action result (or conversational intent) into prose.

        For conversational intents the ``result`` dict is ignored and the reply
        is drawn from the static templates, disambiguated by keywords in
        ``message``. Existing action intents ignore ``message`` and render
        ``result`` as before, preserving the historical two-arg signature.
        """
        if intent in cls._CONVERSATIONAL:
            return cls._format_conversational(intent, message)
        return cls.format_result_existing(result, intent)

    @classmethod
    def _format_conversational(cls, intent: str, message: str) -> str:
        """Render a smalltalk/capability/meta/unknown reply from templates."""
        language = cls.detect_language(message)
        responses = cls.load_responses()
        msg_lower = message.lower()

        if intent == "smalltalk":
            block = responses["smalltalk"][language]
            if any(w in msg_lower for w in ["hello", "hi", "hallo", "hey", "guten"]):
                return block.get("greeting", "Hello!")
            if any(w in msg_lower for w in ["thanks", "thank you", "danke", "dank dir"]):
                return block.get("thanks", "You're welcome!")
            if any(w in msg_lower for w in ["bye", "goodbye", "ciao", "auf wiedersehen"]):
                return block.get("goodbye", "See you!")
            return block["greeting"]

        if intent == "capability":
            return responses["capability"][language]["default"]

        if intent == "meta":
            block = responses["meta"][language]
            if any(w in msg_lower for w in ["model", "modell", "which ai", "welch"]):
                return block["model"]
            if any(w in msg_lower for w in ["local", "lokal", "offline", "my machine"]):
                return block["local"]
            if any(w in msg_lower for w in ["data", "daten", "see", "sehen", "project"]):
                return block["data"]
            return block["model"]

        # unknown
        suggestions = ["create a risk", "list risks", "show plan"]
        return responses["unknown"][language].replace(
            "[suggestions]", " / ".join(suggestions)
        )

    @staticmethod
    def format_result_existing(result: dict[str, Any], intent: str) -> str:
        """Convert an action result into user-facing prose."""
        if "error" in result:
            return f"Sorry, I encountered an error: {result['error']}"

        action = result.get("action", "")

        if intent == "create_risk" and action == "created":
            return (
                f"Created risk: {result.get('title', 'Untitled')} "
                f"(severity: {result.get('severity')})"
            )
        if intent == "create_task" and action == "created":
            return (
                f"Created task: {result.get('title')} "
                f"(priority: {result.get('priority')})"
            )
        if intent == "list_risks" and action == "list":
            count = result.get("count", 0)
            titles = [r.get("title", "?") for r in result.get("risks", [])[:3]]
            preview = ", ".join(titles) if titles else "none"
            return f"Found {count} risks. Top ones: {preview}"
        if intent == "show_plan" and action == "show":
            return f"Current plan: {result.get('plan', result.get('summary', 'No plan yet'))}"
        if intent == "review_status" and action == "status":
            return f"Latest review verdict: {result.get('verdict')}"
        if intent == "run_review" and action == "enqueued":
            return f"Review queued (Job ID: {result.get('job_id')})"
        if action == "answer":
            return result.get("answer", "I'm not sure.")
        return str(result)


class ChatService:
    """Orchestrate a full chat turn: classify, execute, format, persist."""

    def __init__(
        self,
        store: ChatStore,
        router: IntentRouter,
        executor: ActionExecutor,
        llm_client: Any,
    ) -> None:
        self.store = store
        self.router = router
        self.executor = executor
        self.llm_client = llm_client

    # ------------------------------------------------------------------ #
    def handle_turn(
        self,
        message: str,
        project_id: str,
        session_id: str | None = None,
    ) -> AssistantTurn:
        """Process one user message and return the assistant's response."""
        # 1. Load or create the session.
        session = None
        if session_id:
            session = self.store.get_session(session_id)
        if session is None:
            session = self.store.create_session(project_id)

        # 2. Persist the user message.
        user_msg = self.store.add_message(
            session.id,
            ChatRole.user,
            message,
            {"tokens": len(message.split())},
        )

        # 3. Assemble project context (kept minimal here; the API layer is
        #    responsible for hydrating risks/plan/tasks when wired to stores).
        context = ChatContext(project_id=project_id)

        # 4. Classify intent (degrade gracefully on any router failure).
        classification = self._classify(message, context)

        # 5. Execute the action, or handle a conversational intent.
        #    Conversational intents (smalltalk/capability/meta/unknown) are
        #    answered from static templates with no side effect and no LLM call.
        high_confidence = classification.confidence >= _CONFIDENCE_THRESHOLD
        conversational = classification.intent in ResponseFormatter._CONVERSATIONAL
        if conversational:
            result = {"action": "conversational"}
            response_text = ResponseFormatter.format_result(
                result, classification.intent, message
            )
        elif high_confidence:
            result = self.executor.execute(
                classification.intent, classification.params, context
            )
            response_text = ResponseFormatter.format_result(
                result, classification.intent, message
            )
        else:
            # Low confidence and not a recognised conversational intent:
            # degrade to the improved "unknown" fallback (suggestions).
            result = {"action": "conversational"}
            response_text = ResponseFormatter.format_result(result, "unknown", message)

        # H1: Guard BEFORE persistence — validate response before writing to store.
        # Lazy import avoids the circular dependency:
        #   server.py → chat_api.py → service.py → (lazy) server.py
        # All modules are fully initialised by the time handle_turn is called.
        from hermes_assistant.webapp.server import _validate_safe_json  # noqa: PLC0415

        violations = _validate_safe_json(_json.dumps({"content": response_text}))
        if violations:
            logger.warning(
                "Confidentiality guard blocked assistant response for session %s: %s",
                session.id,
                "; ".join(violations),
            )
            raise ConfidentialityGuardError("Content validation failed")

        # 6. Persist the assistant message.
        assistant_msg = self.store.add_message(
            session.id,
            ChatRole.assistant,
            response_text,
            {
                "intent": classification.intent,
                "confidence": classification.confidence,
            },
        )

        # 7. Persist the action (skip conversational intents — no side effect).
        action = None
        if not conversational and high_confidence:
            action = self.store.add_action(
                session.id,
                user_msg.id,
                classification.intent,
                classification.params,
                result,
            )

        # 9. Touch the session so it sorts to the top of recency lists.
        self.store.touch_session(session.id)

        # 10. Follow-up suggestions.
        suggestions = self._build_suggestions(context, classification)

        return AssistantTurn(
            session_id=session.id,
            message=assistant_msg,
            action=action,
            suggestions=suggestions,
        )

    # ------------------------------------------------------------------ #
    def _classify(self, message: str, context: ChatContext) -> IntentClassification:
        """Classify intent, degrading to a safe fallback on any error."""
        try:
            return self.router.classify(message, context)
        except Exception:  # noqa: BLE001 - LLM/transport failures must not 500
            return IntentClassification(
                intent="answer_question", params={}, confidence=0.0
            )

    def _build_suggestions(
        self, context: ChatContext, classification: IntentClassification
    ) -> list[str]:
        """Generate up to three context-aware follow-up suggestions."""
        suggestions: list[str] = []
        if not context.risks and context.open_task_count == 0:
            suggestions.append("Create a risk to get started")
        if classification.intent == "list_risks":
            suggestions.append("Want to create a risk?")
        if context.latest_verdict == "fail":
            suggestions.append("Run a review to check progress")
        return suggestions[:3]
