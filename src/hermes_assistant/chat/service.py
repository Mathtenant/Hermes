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

_CONFIDENCE_THRESHOLD = 0.7


class ResponseFormatter:
    """Render an executor result dict into a natural-language reply."""

    @staticmethod
    def format_result(result: dict[str, Any], intent: str) -> str:
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

        # 5. Execute the action, or fall back to a grounded answer.
        high_confidence = classification.confidence >= _CONFIDENCE_THRESHOLD
        if high_confidence and classification.intent != "smalltalk":
            result = self.executor.execute(
                classification.intent, classification.params, context
            )
        elif classification.intent == "smalltalk":
            result = {"action": "answer", "answer": "Hi! How can I help with your project?"}
        else:
            result = {
                "action": "answer",
                "answer": self._fallback_answer(message, context),
            }

        # 6. Format the reply.
        response_text = ResponseFormatter.format_result(result, classification.intent)

        # 7. Persist the assistant message.
        assistant_msg = self.store.add_message(
            session.id,
            ChatRole.assistant,
            response_text,
            {
                "intent": classification.intent,
                "confidence": classification.confidence,
            },
        )

        # 8. Persist the action (skip pure smalltalk).
        action = None
        if classification.intent != "smalltalk":
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

    def _fallback_answer(self, message: str, context: ChatContext) -> str:
        """Produce a safe, non-committal answer when confidence is low.

        Intentionally does not call the LLM: this path is reached when the
        router is unavailable or unsure, so we return a deterministic prompt
        for clarification rather than risk a hallucinated answer.
        """
        return (
            "I'm here to help with risks, tasks, plans, and reviews. "
            "Could you rephrase what you'd like to do?"
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
