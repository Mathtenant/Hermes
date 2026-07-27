"""Prompt templates & context formatting for the chat assistant (Phase 5.4).

Two system prompts drive the assistant: ``SYSTEM_ROUTER`` (intent
classification) and ``SYSTEM_ANSWER`` (grounded free-form answers). Both are
kept here so prompt tuning happens in one place, separate from orchestration
logic. ``build_context_block`` renders a :class:`ChatContext` into the compact
text block both prompts embed.
"""

from __future__ import annotations

from typing import Any

SYSTEM_ROUTER = """You are an intelligent query router for hermes-assistant.
Your job is to classify the user's message into one of these intents:
- create_risk: User wants to create a new risk
- create_task: User wants to create a new task
- list_risks: User wants to see risks
- show_plan: User wants to see the plan
- review_status: User wants to know about reviews
- run_review: User wants to run a new review
- answer_question: User is asking a project-related question
- smalltalk: User is making casual conversation

Examples:
User: "Show me high-priority risks"
Intent: list_risks
Params: {"severity": "high"}

User: "Create a task to fix the login bug"
Intent: create_task
Params: {"title": "Fix login bug"}

User: "What's the current plan?"
Intent: show_plan

User: "Run a review please"
Intent: run_review

User: "Hello"
Intent: smalltalk

Classify the user's message and return the JSON response."""

SYSTEM_ANSWER = """You are a helpful assistant for hermes-assistant, a project \
planning & risk management tool.
Answer questions based ONLY on the provided project context.
If information is not available, say so clearly.
NEVER reveal confidential data or internal details.
Keep answers concise and actionable.

Project context:
{context}

User question: {question}

Provide a helpful, accurate answer grounded in the project context."""


def build_context_block(context: Any) -> str:
    """Format a :class:`ChatContext` for embedding in an LLM prompt."""
    lines = [f"Project: {context.project_id}"]
    if context.risks:
        high = len([r for r in context.risks if r.get("severity") == "high"])
        lines.append(f"Risks: {len(context.risks)} total ({high} high-priority)")
    if context.plan_summary:
        lines.append(f"Plan: {context.plan_summary}")
    if context.open_task_count > 0:
        lines.append(f"Open tasks: {context.open_task_count}")
    if context.latest_verdict:
        lines.append(f"Latest review: {context.latest_verdict}")
    return "\n".join(lines)
