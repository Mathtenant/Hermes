"""Action executor for the chat assistant (Phase 5.3).

Dispatches a classified intent to a concrete side effect against the domain
stores (:class:`RiskRegistry`, :class:`TaskStore`, :class:`PlanEditor`). Every
handler returns a plain JSON-serialisable dict so the result can be persisted
in ``chat_actions`` and rendered by the :class:`ResponseFormatter`.

The stores are injected, so the executor is agnostic to whether it is talking
to a real SQLite-backed store or an in-memory fake (as used in unit tests).
Handlers defensively normalise domain objects (e.g. a :class:`Risk` model) to
dicts so the same code path works for both.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

from hermes_assistant.tasks.pendenzen import Pendenz, PendenzSource


def _as_dict(obj: Any) -> dict[str, Any]:
    """Normalise a domain object (Pydantic model or dict) to a JSON dict."""
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return dict(obj)


class ActionExecutor:
    """Execute chat actions against the injected domain stores."""

    def __init__(self, risk_registry: Any, task_store: Any, plan_editor: Any) -> None:
        self.risks = risk_registry
        self.tasks = task_store
        self.plans = plan_editor

    # ------------------------------------------------------------------ #
    def execute(
        self, action_type: str, params: dict[str, Any], context: Any
    ) -> dict[str, Any]:
        """Dispatch ``action_type`` to its handler, catching any error.

        Unknown actions and handler exceptions both surface as an
        ``{"error": ...}`` dict rather than raising, so the orchestrating
        service can always produce a user-facing reply.
        """
        handlers = {
            "create_risk": self.create_risk,
            "create_task": self.create_task,
            "list_risks": self.list_risks,
            "show_plan": self.show_plan,
            "review_status": self.review_status,
            "run_review": self.run_review,
            "answer_question": self.answer_question,
        }
        handler = handlers.get(action_type)
        if handler is None:
            return {"error": f"Unknown action type: {action_type}"}
        try:
            return handler(params, context)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user as text
            logger.warning("Handler for %r raised: %s", action_type, exc)
            return {"error": str(exc)}

    # ------------------------------------------------------------------ #
    def create_risk(self, params: dict[str, Any], context: Any) -> dict[str, Any]:
        """Create a new risk from extracted params."""
        title = params.get("title", "Untitled Risk")
        risk = self.risks.create(
            title=title,
            description=params.get("description", ""),
            severity=params.get("severity", "medium"),
            likelihood=int(params.get("likelihood", 3)),
            owner=params.get("owner", ""),
            confidential=bool(params.get("confidential", False)),
        )
        severity = getattr(risk.severity, "value", risk.severity)
        return {
            "action": "created",
            "risk_id": risk.id,
            "title": risk.title,
            "severity": severity,
        }

    def create_task(self, params: dict[str, Any], context: Any) -> dict[str, Any]:
        """Create a new task (pendenz) from extracted params."""
        title = params.get("title", "Untitled Task")
        priority = params.get("priority", "medium")
        pendenz = Pendenz(
            id="",  # store assigns a UUID
            title=title,
            description=params.get("description", ""),
            owner=params.get("owner"),
            priority=priority,
            source=PendenzSource.manual,
            source_ref=params.get("source_ref"),
        )
        task_id = self.tasks.create(pendenz)
        return {
            "action": "created",
            "task_id": task_id,
            "title": title,
            "priority": priority,
        }

    def list_risks(self, params: dict[str, Any], context: Any) -> dict[str, Any]:
        """List non-confidential risks, optionally filtered by severity."""
        # export_public() excludes confidential risks by construction.
        risks_data = [_as_dict(r) for r in self.risks.export_public()]

        severity_filter = params.get("severity")
        if severity_filter:
            risks_data = [
                r for r in risks_data if r.get("severity") == severity_filter
            ]
        risks_data.sort(key=lambda r: r.get("likelihood", 0), reverse=True)

        return {
            "action": "list",
            "count": len(risks_data),
            "risks": risks_data[:10],
        }

    def show_plan(self, params: dict[str, Any], context: Any) -> dict[str, Any]:
        """Return the current plan summary from context or the plan store."""
        if context.plan_summary:
            return {"action": "show", "plan": context.plan_summary}

        plans = self.plans.list_plans()
        if not plans:
            return {"error": "No plan found"}

        first = plans[0]
        if isinstance(first, str):
            version = self.plans.get(first)
            count = len(version.items) if version is not None else 0
            return {
                "action": "show",
                "plan_id": first,
                "summary": f"{count} outcomes planned",
            }
        # Fake/dict plan shape used in unit tests.
        return {
            "action": "show",
            "plan_id": first.get("plan_id"),
            "summary": f"{len(first.get('items', []))} outcomes planned",
        }

    def review_status(self, params: dict[str, Any], context: Any) -> dict[str, Any]:
        """Return the latest review verdict from context, if any."""
        if context.latest_verdict:
            return {"action": "status", "verdict": context.latest_verdict}
        return {"error": "No review history found"}

    def run_review(self, params: dict[str, Any], context: Any) -> dict[str, Any]:
        """Enqueue a review (non-blocking placeholder job id)."""
        job_id = uuid.uuid4().hex[:8]
        return {"action": "enqueued", "job_id": job_id, "status": "pending"}

    def answer_question(self, params: dict[str, Any], context: Any) -> dict[str, Any]:
        """Answer common questions about the project using keyword heuristics.

        Routes by keyword to return actual project data from the pre-hydrated
        ChatContext rather than deferring to a data lookup that never happens.
        The context already carries risks, plan_summary, and open_task_count,
        mirroring the pattern used in show_plan and review_status.
        """
        question = params.get("message", params.get("question", "")).lower()

        # Risk-related questions
        if any(w in question for w in ["risk", "threat", "danger"]):
            risks: list[dict] = getattr(context, "risks", None) or []
            if risks:
                titles = [r.get("title", "?") for r in risks[:3]]
                return {
                    "action": "answer",
                    "answer": (
                        f"Current risks: {', '.join(titles)}. "
                        f"Total: {len(risks)} risks tracked."
                    ),
                }
            return {
                "action": "answer",
                "answer": "No risks are currently tracked for this project.",
            }

        # Plan-related questions
        if any(w in question for w in ["plan", "phase", "timeline", "schedule", "duration"]):
            plan_summary: str | None = getattr(context, "plan_summary", None)
            if plan_summary:
                return {"action": "answer", "answer": f"Plan summary: {plan_summary}"}
            # Fall back to store query when context has no pre-hydrated summary.
            plan_ids = self.plans.list_plans()
            if plan_ids:
                first = plan_ids[0]
                if isinstance(first, str):
                    version = self.plans.get(first)
                    count = len(version.items) if version is not None else 0
                else:
                    count = len(first.get("items", []))
                return {
                    "action": "answer",
                    "answer": f"The project plan has {count} phases/items.",
                }
            return {
                "action": "answer",
                "answer": "No plan is currently set for this project.",
            }

        # Task / pendenzen questions
        if any(w in question for w in ["task", "todo", "pendenz", "action"]):
            task_count: int = getattr(context, "open_task_count", 0)
            if task_count > 0:
                return {
                    "action": "answer",
                    "answer": f"You have {task_count} open tasks for this project.",
                }
            return {
                "action": "answer",
                "answer": "No open tasks for this project.",
            }

        # Fallback: surface capabilities
        return {
            "action": "answer",
            "answer": (
                "I can help with risks, plans, and tasks. "
                "Try asking: 'What risks are we tracking?' or 'How long is the plan?'"
            ),
        }
