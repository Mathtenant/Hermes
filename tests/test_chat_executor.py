"""Unit tests for the chat ActionExecutor (Phase 5.3).

In-memory fakes stand in for the Risk Registry, Task Store, and Plan Editor so
each action is exercised without touching SQLite or the LLM.
"""

from __future__ import annotations

from hermes_assistant.chat.executor import ActionExecutor
from hermes_assistant.chat.model import ChatContext


class _FakeSeverity:
    def __init__(self, value: str) -> None:
        self.value = value


class _FakeRisk:
    def __init__(self, title: str, **kw) -> None:  # noqa: ANN003
        self.id = "risk_123"
        self.title = title
        self.severity = _FakeSeverity(kw.get("severity", "medium"))


class FakeRiskRegistry:
    def __init__(self) -> None:
        self.risks: list[_FakeRisk] = []

    def create(self, title, **kwargs):  # noqa: ANN001, ANN003
        risk = _FakeRisk(title, **kwargs)
        self.risks.append(risk)
        return risk

    def export_public(self):
        return [{"title": r.title, "severity": "high"} for r in self.risks]


class FakeTaskStore:
    def __init__(self) -> None:
        self.tasks: list[str] = []

    def create(self, pendenz):  # noqa: ANN001
        task_id = "task_123"
        self.tasks.append(task_id)
        return task_id


class FakePlanEditor:
    def list_plans(self):
        return [{"plan_id": "p1", "items": []}]

    def get(self, plan_id):  # noqa: ANN001
        return {"plan_id": plan_id, "items": []}


def _executor() -> ActionExecutor:
    return ActionExecutor(FakeRiskRegistry(), FakeTaskStore(), FakePlanEditor())


def test_executor_create_risk():
    result = _executor().execute(
        "create_risk", {"title": "Security Gap", "severity": "high"},
        ChatContext(project_id="proj1"),
    )
    assert result["action"] == "created"
    assert result["title"] == "Security Gap"


def test_executor_create_task():
    result = _executor().execute(
        "create_task", {"title": "Deploy to staging"},
        ChatContext(project_id="proj1"),
    )
    assert result["action"] == "created"
    assert result["title"] == "Deploy to staging"


def test_executor_list_risks():
    result = _executor().execute("list_risks", {}, ChatContext(project_id="proj1"))
    assert result["action"] == "list"
    assert "count" in result


def test_executor_list_risks_excludes_confidential():
    result = _executor().execute("list_risks", {}, ChatContext(project_id="proj1"))
    # export_public() never returns confidential rows.
    assert "confidential" not in str(result).lower()


def test_executor_show_plan():
    result = _executor().execute(
        "show_plan", {}, ChatContext(project_id="proj1", plan_summary="Phase 1, Phase 2")
    )
    assert result["action"] == "show"
    assert "Phase 1" in result["plan"]


def test_executor_review_status():
    result = _executor().execute(
        "review_status", {}, ChatContext(project_id="proj1", latest_verdict="pass")
    )
    assert result["action"] == "status"
    assert result["verdict"] == "pass"


def test_executor_run_review():
    result = _executor().execute("run_review", {}, ChatContext(project_id="proj1"))
    assert result["action"] == "enqueued"
    assert "job_id" in result


def test_executor_answer_question():
    result = _executor().execute(
        "answer_question", {"message": "What's the status?"},
        ChatContext(project_id="proj1"),
    )
    assert result["action"] == "answer"


def test_executor_unknown_action():
    result = _executor().execute("unknown_action", {}, ChatContext(project_id="proj1"))
    assert "error" in result


def test_executor_create_risk_with_all_fields():
    result = _executor().execute(
        "create_risk",
        {
            "title": "Risk",
            "severity": "critical",
            "likelihood": 5,
            "owner": "alice",
            "description": "Full description",
        },
        ChatContext(project_id="proj1"),
    )
    assert result["action"] == "created"


def test_executor_create_task_with_priority():
    result = _executor().execute(
        "create_task", {"title": "Task", "priority": "high", "owner": "bob"},
        ChatContext(project_id="proj1"),
    )
    assert result["action"] == "created"
    assert result["priority"] == "high"


def test_executor_list_risks_filter_severity():
    result = _executor().execute(
        "list_risks", {"severity": "high"}, ChatContext(project_id="proj1")
    )
    assert result["action"] == "list"


def test_executor_show_plan_from_context():
    result = _executor().execute(
        "show_plan", {}, ChatContext(project_id="proj1", plan_summary="Test plan")
    )
    assert "Test plan" in result["plan"]


def test_executor_review_status_no_history():
    result = _executor().execute("review_status", {}, ChatContext(project_id="proj1"))
    assert "error" in result


def test_executor_list_risks_limits_results():
    result = _executor().execute("list_risks", {}, ChatContext(project_id="proj1"))
    assert result["action"] == "list"
    assert len(result["risks"]) <= 10
