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
    # Generic unknown question → capability fallback
    result = _executor().execute(
        "answer_question", {"message": "What's the status?"},
        ChatContext(project_id="proj1"),
    )
    assert result["action"] == "answer"
    assert "risk" in result["answer"].lower() or "plan" in result["answer"].lower()


# --------------------------------------------------------------------------- #
# M1 — heuristic answer_question paths
# --------------------------------------------------------------------------- #


def test_answer_question_risk_keyword_returns_risk_list():
    ctx = ChatContext(
        project_id="proj1",
        risks=[
            {"title": "Data Breach", "severity": "high"},
            {"title": "Budget Overrun", "severity": "medium"},
        ],
    )
    result = _executor().execute("answer_question", {"message": "What risks do we have?"}, ctx)
    assert result["action"] == "answer"
    assert "Data Breach" in result["answer"]
    assert "2 risks tracked" in result["answer"]


def test_answer_question_threat_keyword_matches_risk_path():
    ctx = ChatContext(project_id="proj1", risks=[{"title": "SQL Injection", "severity": "critical"}])
    result = _executor().execute("answer_question", {"message": "Any threat to report?"}, ctx)
    assert "SQL Injection" in result["answer"]


def test_answer_question_risk_caps_at_three_titles():
    ctx = ChatContext(
        project_id="proj1",
        risks=[
            {"title": "R1", "severity": "high"},
            {"title": "R2", "severity": "high"},
            {"title": "R3", "severity": "medium"},
            {"title": "R4", "severity": "low"},
        ],
    )
    result = _executor().execute("answer_question", {"message": "What are the risks?"}, ctx)
    # Answer must mention the first 3 titles but not the 4th.
    assert "R1" in result["answer"]
    assert "R3" in result["answer"]
    assert "R4" not in result["answer"]
    assert "4 risks tracked" in result["answer"]


def test_answer_question_risk_empty_project():
    ctx = ChatContext(project_id="proj1", risks=[])
    result = _executor().execute("answer_question", {"message": "Are there any risks?"}, ctx)
    assert result["action"] == "answer"
    assert "no risks" in result["answer"].lower()


def test_answer_question_plan_keyword_uses_context_summary():
    ctx = ChatContext(project_id="proj1", plan_summary="Phase 1: Setup (10 days), Phase 2: Build (20 days)")
    result = _executor().execute("answer_question", {"message": "Tell me the plan"}, ctx)
    assert result["action"] == "answer"
    assert "Phase 1" in result["answer"]


def test_answer_question_timeline_keyword_matches_plan_path():
    ctx = ChatContext(project_id="proj1", plan_summary="2 phases, 30 days total")
    result = _executor().execute("answer_question", {"message": "What is the timeline?"}, ctx)
    assert "2 phases" in result["answer"]


def test_answer_question_plan_falls_back_to_store_when_no_summary():
    # No plan_summary in context → should query the plan store (FakePlanEditor returns 0 items)
    ctx = ChatContext(project_id="proj1")
    result = _executor().execute("answer_question", {"message": "What is the plan?"}, ctx)
    assert result["action"] == "answer"
    assert "phase" in result["answer"].lower() or "plan" in result["answer"].lower()


def test_answer_question_plan_empty_project():
    class _EmptyPlanEditor:
        def list_plans(self):
            return []

        def get(self, plan_id):  # noqa: ANN001
            return None

    exc = ActionExecutor(FakeRiskRegistry(), FakeTaskStore(), _EmptyPlanEditor())
    ctx = ChatContext(project_id="proj1")
    result = exc.execute("answer_question", {"message": "What is the plan?"}, ctx)
    assert result["action"] == "answer"
    assert "no plan" in result["answer"].lower()


def test_answer_question_task_keyword_returns_count():
    ctx = ChatContext(project_id="proj1", open_task_count=5)
    result = _executor().execute("answer_question", {"message": "What tasks are open?"}, ctx)
    assert result["action"] == "answer"
    assert "5 open tasks" in result["answer"]


def test_answer_question_pendenz_keyword_matches_task_path():
    ctx = ChatContext(project_id="proj1", open_task_count=2)
    result = _executor().execute("answer_question", {"message": "Zeige meine Pendenzen"}, ctx)
    assert "2 open tasks" in result["answer"]


def test_answer_question_task_empty_project():
    ctx = ChatContext(project_id="proj1", open_task_count=0)
    result = _executor().execute("answer_question", {"message": "Do I have any tasks?"}, ctx)
    assert result["action"] == "answer"
    assert "no open tasks" in result["answer"].lower()


def test_answer_question_unknown_returns_capability_fallback():
    ctx = ChatContext(project_id="proj1")
    result = _executor().execute("answer_question", {"message": "Who wrote this?"}, ctx)
    assert result["action"] == "answer"
    # Fallback must mention at least one capability keyword
    answer = result["answer"].lower()
    assert any(w in answer for w in ["risk", "plan", "task"])


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


# --------------------------------------------------------------------------- #
# H4 — executor logs exceptions server-side
# --------------------------------------------------------------------------- #


def test_executor_exception_is_logged(caplog) -> None:
    """H4: Exceptions from a handler are logged at WARNING level before returning."""
    import logging

    class _BrokenRiskRegistry:
        def create(self, **kw):  # noqa: ANN003
            raise RuntimeError("UNIQUE constraint failed: risks.id")

        def export_public(self):
            return []

    exc = ActionExecutor(_BrokenRiskRegistry(), FakeTaskStore(), FakePlanEditor())
    with caplog.at_level(logging.WARNING, logger="hermes_assistant.chat.executor"):
        result = exc.execute("create_risk", {"title": "Dup"}, ChatContext(project_id="p1"))

    assert "error" in result
    assert "Handler for" in caplog.text
    assert "UNIQUE constraint failed" in caplog.text
