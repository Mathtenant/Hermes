"""Intent router for the chat assistant (Phase 5.2).

Classifies a user message into one of eight intents using the ROUTER model
(qwen3:4b) via grammar-constrained structured output. The router is a thin
wrapper: it assembles a grounded system prompt from :class:`ChatContext`, then
delegates to the injected LLM client. The client is duck-typed (Protocol) so
tests can substitute a deterministic fake without touching Ollama.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .model import ChatContext, IntentClassification


@runtime_checkable
class LLMClient(Protocol):
    """Minimal structured-output surface the router depends on.

    Duck-typed so tests can inject a fake. The real
    :class:`hermes_assistant.llm.client.OllamaClient` satisfies the
    ``structured`` signature (extra kwargs are forwarded via ``**kwargs``).
    """

    def structured(
        self,
        model: str,
        messages: list[dict],
        schema: type,
        **kwargs: object,
    ) -> object:
        """Return a validated instance of ``schema`` (or its dict form)."""
        ...


_SYSTEM_TEMPLATE = """You are an intelligent assistant for hermes-assistant, a \
project planning & risk management tool.
Classify the user's message into one of these intents:
- create_risk: User wants to create a new risk
- create_task: User wants to create a task/pendenz
- list_risks: User wants to see risks (optionally filtered)
- show_plan: User wants to see the current plan
- review_status: User wants to know about review results
- run_review: User wants to run a new review
- answer_question: User is asking a question about the project
- smalltalk: User is making casual conversation

Examples:
"Show me the high-priority risks" -> list_risks (params: priority=high)
"Create a task to fix the security issue" -> create_task (params: title="Fix security issue")
"What's the plan?" -> show_plan
"Run a review" -> run_review

Current project context:
{context}

Respond with only the intent classification in the specified JSON format."""


class IntentRouter:
    """Classify user messages into intents using the ROUTER model."""

    def __init__(self, client: LLMClient, model: str = "qwen3:4b") -> None:
        """Wire the router to an LLM client and a model id.

        Args:
            client: Anything satisfying the :class:`LLMClient` protocol.
            model: Router model id. Defaults to the roster ROUTER (qwen3:4b).
        """
        self.client = client
        self.model = model

    def classify(self, message: str, context: ChatContext) -> IntentClassification:
        """Classify ``message`` into one of the eight intents.

        The classification is grounded in ``context`` (risks, plan, tasks,
        latest verdict), which is embedded in the system prompt.
        """
        context_block = self._build_context_block(context)
        system_prompt = _SYSTEM_TEMPLATE.format(context=context_block)

        messages = [{"role": "user", "content": message}]

        result = self.client.structured(
            self.model,
            messages,
            IntentClassification,
            system=system_prompt,
            num_ctx=4096,
        )
        if isinstance(result, IntentClassification):
            return result
        if isinstance(result, dict):
            return IntentClassification(**result)
        # Pydantic model of a different type or unexpected shape.
        return IntentClassification.model_validate(result)

    def _build_context_block(self, context: ChatContext) -> str:
        """Format :class:`ChatContext` into a compact prompt block."""
        lines = [f"Project: {context.project_id}"]
        if context.risks:
            lines.append(f"Risks: {len(context.risks)} total")
            high_risks = [r for r in context.risks if r.get("severity") == "high"]
            if high_risks:
                lines.append(f"  - {len(high_risks)} high-severity")
        if context.plan_summary:
            lines.append(f"Plan: {context.plan_summary}")
        if context.open_task_count > 0:
            lines.append(f"Open tasks: {context.open_task_count}")
        if context.latest_verdict:
            lines.append(f"Latest review: {context.latest_verdict}")
        return "\n".join(lines)
