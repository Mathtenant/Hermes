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
import re
from collections.abc import Iterator
from typing import Any

from hermes_assistant.config import settings
from hermes_assistant.llm.roster import ModelRole, get_model

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

# The roster's routing model, used as the second choice when the active chat
# model stops answering. Read once: the roster is static config, not state.
_ROUTER_MODEL = get_model(ModelRole.ROUTER)


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

    # Sentinel intent used when the router could not reach the model at all.
    # Handled like a conversational intent (no side effect, no executor call)
    # but rendered from its own template so a setup problem is not disguised
    # as "I understood you but don't know how to help".
    LLM_UNAVAILABLE = "llm_unavailable"

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
    def detect_language(text: str) -> str:
        """Detect language from message content using keyword heuristics.

        Returns 'de', 'fr', or 'en' (default fallback).

        German umlauts/ß are treated as an unambiguous signal and trigger
        an early return before word-level matching.  Common German and French
        function words are used for umlaut-free text (e.g. "Was kannst du?",
        "Pouvez-vous?").
        """
        # Unambiguous German signal — fast path avoids false positives from
        # short French texts that contain no accented characters.
        if any(c in text for c in "äöüßÄÖÜ"):
            return "de"

        words = re.findall(r"\w+", text.lower())

        # German indicators (common function words and modal verbs)
        de_words = {"ich", "das", "ist", "kannst", "du", "können", "macht", "haben", "nicht"}
        de_count = sum(1 for word in words if word in de_words)

        # French indicators (common articles, pronouns, and verbs)
        fr_words = {"je", "le", "la", "les", "vous", "pouvez", "faire", "cela"}
        fr_count = sum(1 for word in words if word in fr_words)

        if de_count >= 1 and de_count >= fr_count:
            return "de"
        if fr_count >= 1:
            return "fr"
        return "en"

    @classmethod
    def _block(cls, key: str, language: str) -> Any:
        """Return the template block for ``key``/``language``, falling back to en.

        ``detect_language`` may return a language a block does not translate;
        without this fallback that would raise KeyError and 500 the turn.
        """
        entry = cls.load_responses()[key]
        if isinstance(entry, dict) and language not in entry:
            return entry["en"]
        return entry[language] if isinstance(entry, dict) else entry

    @classmethod
    def format_result(
        cls,
        result: dict[str, Any],
        intent: str,
        message: str = "",
        model: str = "",
    ) -> str:
        """Convert an action result (or conversational intent) into prose.

        For conversational intents the ``result`` dict is ignored and the reply
        is drawn from the static templates, disambiguated by keywords in
        ``message``. Existing action intents ignore ``message`` and render
        ``result`` as before, preserving the historical two-arg signature.

        ``model`` is the active chat model id. It fills the ``[model]``
        placeholder so "what model are you?" answers truthfully after a
        runtime model swap instead of naming a hard-coded one.
        """
        if intent == cls.LLM_UNAVAILABLE:
            return cls._format_unavailable(
                message, str(result.get("reason", "")), model
            )
        if intent in cls._CONVERSATIONAL:
            return cls._format_conversational(intent, message, model)
        return cls.format_result_existing(result, intent)

    @staticmethod
    def _with_model(template: str, model: str) -> str:
        """Fill the ``[model]`` placeholder with the active model id."""
        return template.replace("[model]", model or "a local model")

    @classmethod
    def _format_unavailable(cls, message: str, reason: str, model: str = "") -> str:
        """Render the 'local model unreachable' reply, naming the real cause."""
        language = cls.detect_language(message)
        template = cls._block(cls.LLM_UNAVAILABLE, language)
        return template.replace("[reason]", reason or "no detail available").replace(
            "[model]", model or "the chat model"
        )

    @classmethod
    def _format_conversational(
        cls, intent: str, message: str, model: str = ""
    ) -> str:
        """Render a smalltalk/capability/meta/unknown reply from templates."""
        language = cls.detect_language(message)
        msg_lower = message.lower()

        if intent == "smalltalk":
            block = cls._block("smalltalk", language)
            if any(w in msg_lower for w in ["hello", "hi", "hallo", "hey", "guten"]):
                return block.get("greeting", "Hello!")
            if any(w in msg_lower for w in ["thanks", "thank you", "danke", "dank dir"]):
                return block.get("thanks", "You're welcome!")
            if any(w in msg_lower for w in ["bye", "goodbye", "ciao", "auf wiedersehen"]):
                return block.get("goodbye", "See you!")
            return block["greeting"]

        if intent == "capability":
            return cls._block("capability", language)["default"]

        if intent == "meta":
            block = cls._block("meta", language)
            if any(w in msg_lower for w in ["model", "modell", "which ai", "welch"]):
                return cls._with_model(block["model"], model)
            if any(w in msg_lower for w in ["local", "lokal", "offline", "my machine"]):
                return block["local"]
            if any(w in msg_lower for w in ["data", "daten", "see", "sehen", "project"]):
                return block["data"]
            return cls._with_model(block["model"], model)

        # unknown
        suggestions = ["create a risk", "list risks", "show plan"]
        return cls._block("unknown", language).replace(
            "[suggestions]", " / ".join(suggestions)
        )

    @staticmethod
    def format_result_existing(result: dict[str, Any], intent: str) -> str:
        """Convert an action result into user-facing prose."""
        if "error" in result:
            # H4: Normalize internal error strings before they reach the user.
            error_msg = result["error"]
            if "UNIQUE constraint failed" in error_msg:
                user_message = "A risk with this ID already exists."
            elif "not found" in error_msg.lower():
                user_message = "The requested item was not found."
            else:
                user_message = "The action could not be completed. Please try again."
            logger.warning("Executor error for intent=%s: %s", intent, error_msg)
            return user_message

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
        # H3: No handler matched — log for debugging and return a safe fallback.
        logger.warning("Unhandled result format for intent=%s: %r", intent, result)
        return "I encountered an issue processing that request. Please try again."


class ChatService:
    """Orchestrate a full chat turn: classify, execute, format, persist."""

    def __init__(
        self,
        store: ChatStore,
        router: IntentRouter,
        executor: ActionExecutor,
        llm_client: Any,
        risk_registry: Any = None,
        plan_editor: Any = None,
        task_store: Any = None,
    ) -> None:
        self.store = store
        self.router = router
        self.executor = executor
        self.llm_client = llm_client
        # Phase 6 M10: optional stores used to hydrate ChatContext with real
        # project state. All three are optional and backward compatible —
        # when omitted, handle_turn falls back to an empty context exactly
        # as before.
        self.risk_registry = risk_registry
        self.plan_editor = plan_editor
        self.task_store = task_store

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

        # 3. Assemble project context. When risk_registry/task_store are
        #    injected (Phase 6 M10), hydrate real project state so
        #    classification/suggestions/answers are grounded in current
        #    data. Any store failure degrades to an empty context rather
        #    than failing the turn.
        risks: list[dict[str, Any]] = []
        open_task_count = 0
        if self.risk_registry is not None:
            try:
                risks = [r.model_dump(mode="json") for r in self.risk_registry.export_public()]
            except Exception:  # noqa: BLE001 - store failures must not 500 the turn
                risks = []
        if self.task_store is not None:
            try:
                open_task_count = self.task_store.count_open()
            except Exception:  # noqa: BLE001 - store failures must not 500 the turn
                open_task_count = 0

        context = ChatContext(
            project_id=project_id,
            risks=risks,
            open_task_count=open_task_count,
        )

        # 4. Classify intent (degrade gracefully on any router failure).
        classification, failure_reason = self._classify(message, context)

        # 5. Execute the action, or handle a conversational intent.
        #    Conversational intents (smalltalk/capability/meta/unknown) are
        #    answered from static templates with no side effect and no LLM call.
        high_confidence = classification.confidence >= settings.chat_confidence_threshold
        unavailable = bool(failure_reason)
        conversational = (
            classification.intent in ResponseFormatter._CONVERSATIONAL or unavailable
        )
        if unavailable:
            result = {"action": "conversational", "reason": failure_reason}
            response_text = ResponseFormatter.format_result(
                result, ResponseFormatter.LLM_UNAVAILABLE, message, self._model()
            )
        elif conversational:
            result = {"action": "conversational"}
            response_text = ResponseFormatter.format_result(
                result, classification.intent, message, self._model()
            )
        elif high_confidence:
            result = self.executor.execute(
                classification.intent, classification.params, context
            )
            response_text = ResponseFormatter.format_result(
                result, classification.intent, message, self._model()
            )
        else:
            # Low confidence and not a recognised conversational intent:
            # degrade to the improved "unknown" fallback (suggestions).
            result = {"action": "conversational"}
            response_text = ResponseFormatter.format_result(
                result, "unknown", message, self._model()
            )

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
    def stream_turn(
        self,
        message: str,
        project_id: str,
        session_id: str | None = None,
    ) -> Iterator[str | dict]:
        """Stream one chat turn as SSE-ready chunks, persisting once at the end.

        Yields:
            str — a text chunk to send as a ``data:`` SSE event.
            dict with ``"done": True`` — terminal success carrying
                ``message_id``, ``session_id``, and ``suggestions``.
            dict with ``"error": True`` — confidentiality guard blocked the
                assembled response; client should discard received chunks.

        The classify/execute/format pipeline runs synchronously (same as
        :meth:`handle_turn`). Only the formatted answer is yielded word-by-word
        for perceived responsiveness. The guard runs on the fully assembled text;
        on violation an error sentinel is yielded and nothing is persisted.
        """
        # 1. Load or create session.
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

        # 3. Assemble project context.
        risks: list[dict[str, Any]] = []
        open_task_count = 0
        if self.risk_registry is not None:
            try:
                risks = [r.model_dump(mode="json") for r in self.risk_registry.export_public()]
            except Exception:  # noqa: BLE001
                risks = []
        if self.task_store is not None:
            try:
                open_task_count = self.task_store.count_open()
            except Exception:  # noqa: BLE001
                open_task_count = 0

        context = ChatContext(
            project_id=project_id,
            risks=risks,
            open_task_count=open_task_count,
        )

        # 4. Classify intent (degrade gracefully on any router failure).
        classification, failure_reason = self._classify(message, context)

        # 5. Execute the action or handle conversational intent.
        high_confidence = classification.confidence >= settings.chat_confidence_threshold
        unavailable = bool(failure_reason)
        conversational = (
            classification.intent in ResponseFormatter._CONVERSATIONAL or unavailable
        )
        if unavailable:
            result: dict[str, Any] = {
                "action": "conversational",
                "reason": failure_reason,
            }
            response_text = ResponseFormatter.format_result(
                result, ResponseFormatter.LLM_UNAVAILABLE, message, self._model()
            )
        elif conversational:
            result = {"action": "conversational"}
            response_text = ResponseFormatter.format_result(
                result, classification.intent, message, self._model()
            )
        elif high_confidence:
            result = self.executor.execute(
                classification.intent, classification.params, context
            )
            response_text = ResponseFormatter.format_result(
                result, classification.intent, message, self._model()
            )
        else:
            result = {"action": "conversational"}
            response_text = ResponseFormatter.format_result(
                result, "unknown", message, self._model()
            )

        # 6. Yield text word-by-word for perceived responsiveness, buffering
        #    the assembled text for the guard check.
        words = response_text.split()
        assembled_parts: list[str] = []
        for i, word in enumerate(words):
            chunk = word if i == 0 else " " + word
            assembled_parts.append(chunk)
            yield chunk

        assembled = "".join(assembled_parts)

        # 7. Confidentiality guard on fully assembled response.
        from hermes_assistant.webapp.server import _validate_safe_json  # noqa: PLC0415

        violations = _validate_safe_json(_json.dumps({"content": assembled}))
        if violations:
            logger.warning(
                "Confidentiality guard blocked streaming response for session %s: %s",
                session.id,
                "; ".join(violations),
            )
            yield {"error": True, "message": "Internal error"}
            return

        # 8. Persist the assistant message once (never partial content).
        assistant_msg = self.store.add_message(
            session.id,
            ChatRole.assistant,
            assembled,
            {
                "intent": classification.intent,
                "confidence": classification.confidence,
            },
        )

        # 9. Persist the action (skip conversational intents).
        if not conversational and high_confidence:
            self.store.add_action(
                session.id,
                user_msg.id,
                classification.intent,
                classification.params,
                result,
            )

        # 10. Touch session and compute suggestions.
        self.store.touch_session(session.id)
        suggestions = self._build_suggestions(context, classification)

        yield {
            "done": True,
            "message_id": assistant_msg.id,
            "session_id": session.id,
            "suggestions": suggestions,
        }

    # ------------------------------------------------------------------ #
    def _model(self) -> str:
        """Active chat model id, read from the router so swaps are reflected."""
        return getattr(self.router, "model", "") or ""

    def _classify(
        self, message: str, context: ChatContext
    ) -> tuple[IntentClassification, str]:
        """Classify intent, reporting the reason when the model is unreachable.

        Returns the classification plus a failure reason (empty on success).
        A router failure means Ollama is down, the model is not pulled, or the
        request timed out — none of which the user can diagnose from a generic
        "I'm not sure how to help". The reason is surfaced verbatim so the
        setup problem is actionable.
        """
        try:
            return self.router.classify(message, context), ""
        except Exception as exc:  # noqa: BLE001 - LLM/transport failures must not 500
            reason = f"{type(exc).__name__}: {exc}"
            logger.warning("Intent classification failed — %s", reason)

            fallback = self._classify_with_fallback(message, context)
            if fallback is not None:
                return fallback, ""

            # `intent` stays inside its Literal domain — the failure travels in
            # the reason string, so the router's intent vocabulary is not
            # widened with a value the model itself could never return.
            return (
                IntentClassification(intent="unknown", params={}, confidence=0.0),
                reason,
            )

    def _fallback_candidates(self, failed: str) -> list[str]:
        """Installed models worth trying after ``failed`` did not answer.

        Ordered by how likely they are to route well: the configured default
        first, then the roster's router model, then everything else installed,
        alphabetically so the choice is reproducible rather than dict-ordered.

        Returns an empty list when Ollama itself is unreachable — every model
        is behind the same daemon, so trying another one would just repeat the
        same failure more slowly and bury the real cause.
        """
        try:
            health = self.llm_client.health()
        except Exception:  # noqa: BLE001 - health must never raise into a turn
            return []
        if not health.get("available"):
            return []

        installed = [m for m in health.get("models", []) if m and m != failed]
        if not installed:
            return []

        preferred = [
            m for m in (getattr(settings, "chat_model", ""), _ROUTER_MODEL)
            if m and m in installed
        ]
        rest = sorted(m for m in installed if m not in preferred)
        # dict.fromkeys: order-preserving de-duplication, since the configured
        # model and the roster router are often the same id.
        return list(dict.fromkeys([*preferred, *rest]))

    def _classify_with_fallback(
        self, message: str, context: ChatContext
    ) -> IntentClassification | None:
        """Retry classification on the next installed model, switching to it.

        A model that is not pulled, or is corrupt, or dies under memory
        pressure fails every turn, and telling the user to go pull it is a
        worse answer than quietly using one they already have. On success the
        router keeps the working model, so the next turn does not pay for the
        failed one again.

        Returns ``None`` when no other model works, leaving the caller to
        report the original failure.
        """
        failed = self._model()
        for candidate in self._fallback_candidates(failed):
            try:
                classification = self._classify_on(candidate, message, context)
            except Exception as exc:  # noqa: BLE001 - try the next one
                logger.warning("Fallback model %s also failed — %s", candidate, exc)
                continue
            logger.warning(
                "Chat model %s was unreachable; switched to %s", failed, candidate
            )
            self.router.model = candidate
            return classification
        return None

    def _classify_on(
        self, model: str, message: str, context: ChatContext
    ) -> IntentClassification:
        """Classify using ``model``, restoring the router's model on failure.

        The router takes its model from an attribute rather than an argument,
        so a temporary swap is the only way to try a candidate — and it has to
        be undone when the candidate fails, or one bad model would strand the
        router on itself.
        """
        previous = self.router.model
        self.router.model = model
        try:
            return self.router.classify(message, context)
        except Exception:
            self.router.model = previous
            raise

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
