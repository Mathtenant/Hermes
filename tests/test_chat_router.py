"""Unit tests for the chat IntentRouter (Phase 5.2).

A fake LLM client returns a canned classification and records the call, so the
router is tested in isolation from Ollama.
"""

from __future__ import annotations

from hermes_assistant.chat.model import ChatContext, IntentClassification
from hermes_assistant.chat.router import IntentRouter


class FakeLLMClient:
    """Deterministic stand-in for OllamaClient.structured."""

    def __init__(self, canned_response: IntentClassification) -> None:
        self.canned_response = canned_response
        self.last_call: tuple | None = None

    def structured(self, model, messages, schema, **kwargs):  # noqa: ANN001
        self.last_call = (model, messages, schema, kwargs)
        return self.canned_response.model_dump()


def test_router_classify_create_risk():
    client = FakeLLMClient(
        IntentClassification(
            intent="create_risk", params={"title": "Security Risk"}, confidence=0.95
        )
    )
    router = IntentRouter(client)
    result = router.classify("Create a security risk", ChatContext(project_id="proj1"))
    assert result.intent == "create_risk"
    assert result.confidence == 0.95


def test_router_classify_list_risks():
    client = FakeLLMClient(
        IntentClassification(intent="list_risks", params={}, confidence=0.92)
    )
    router = IntentRouter(client)
    result = router.classify("Show me the risks", ChatContext(project_id="proj1"))
    assert result.intent == "list_risks"


def test_router_classify_show_plan():
    client = FakeLLMClient(
        IntentClassification(intent="show_plan", params={}, confidence=0.88)
    )
    router = IntentRouter(client)
    context = ChatContext(project_id="proj1", plan_summary="Phase 1: Design, Phase 2: Build")
    result = router.classify("What's the current plan?", context)
    assert result.intent == "show_plan"


def test_router_classify_create_task():
    client = FakeLLMClient(
        IntentClassification(
            intent="create_task", params={"title": "Deploy to staging"}, confidence=0.90
        )
    )
    router = IntentRouter(client)
    result = router.classify("Create a task to deploy", ChatContext(project_id="proj1"))
    assert result.intent == "create_task"


def test_router_classify_review_status():
    client = FakeLLMClient(
        IntentClassification(intent="review_status", params={}, confidence=0.85)
    )
    router = IntentRouter(client)
    context = ChatContext(project_id="proj1", latest_verdict="pass")
    result = router.classify("How is the review going?", context)
    assert result.intent == "review_status"


def test_router_classify_answer_question():
    client = FakeLLMClient(
        IntentClassification(intent="answer_question", params={}, confidence=0.75)
    )
    router = IntentRouter(client)
    result = router.classify("Who is responsible for this?", ChatContext(project_id="proj1"))
    assert result.intent == "answer_question"


def test_router_classify_smalltalk():
    client = FakeLLMClient(
        IntentClassification(intent="smalltalk", params={}, confidence=0.99)
    )
    router = IntentRouter(client)
    result = router.classify("Hello!", ChatContext(project_id="proj1"))
    assert result.intent == "smalltalk"


def test_router_classify_capability():
    """'What can you do' -> capability intent."""
    client = FakeLLMClient(
        IntentClassification(intent="capability", params={}, confidence=0.95)
    )
    router = IntentRouter(client)
    result = router.classify("What can you do?", ChatContext(project_id="proj1"))
    assert result.intent == "capability"


def test_router_classify_meta():
    """'What model are you' -> meta intent."""
    client = FakeLLMClient(
        IntentClassification(intent="meta", params={}, confidence=0.90)
    )
    router = IntentRouter(client)
    result = router.classify("What model are you?", ChatContext(project_id="proj1"))
    assert result.intent == "meta"


def test_router_classify_unknown():
    """Understood-but-unhandled message -> unknown intent."""
    client = FakeLLMClient(
        IntentClassification(intent="unknown", params={}, confidence=0.80)
    )
    router = IntentRouter(client)
    result = router.classify("Tell me a joke", ChatContext(project_id="proj1"))
    assert result.intent == "unknown"


def test_router_low_confidence_fallback():
    client = FakeLLMClient(
        IntentClassification(intent="answer_question", params={}, confidence=0.65)
    )
    router = IntentRouter(client)
    result = router.classify("Something ambiguous", ChatContext(project_id="proj1"))
    assert result.confidence < 0.7


def test_router_uses_context():
    client = FakeLLMClient(
        IntentClassification(intent="list_risks", params={}, confidence=0.90)
    )
    router = IntentRouter(client)
    context = ChatContext(
        project_id="proj1",
        risks=[{"title": "Risk 1", "severity": "high"}],
        plan_summary="2 phases",
        open_task_count=5,
        latest_verdict="pass",
    )
    router.classify("Show risks", context)

    assert client.last_call is not None
    _model, _messages, _schema, kwargs = client.last_call
    system_prompt = kwargs.get("system", "")
    assert "proj1" in system_prompt
    assert "high" in system_prompt


def test_router_init_default_model():
    client = FakeLLMClient(
        IntentClassification(intent="smalltalk", params={}, confidence=0.9)
    )
    router = IntentRouter(client)
    assert router.model == "qwen3:4b"


def test_router_init_custom_model():
    client = FakeLLMClient(
        IntentClassification(intent="smalltalk", params={}, confidence=0.9)
    )
    router = IntentRouter(client, model="custom_model")
    assert router.model == "custom_model"


# --------------------------------------------------------------------------- #
# Regression: the router must be callable against the *real* client signature.
#
# The FakeLLMClient above absorbs any keyword via **kwargs, which hid a real
# defect: IntentRouter.classify passes `system=`, but OllamaClient.structured
# had no such parameter. Every live turn raised TypeError, ChatService caught
# it, and the user saw the generic "not sure how to help" reply — so the chat
# never worked against Ollama while the suite stayed green.
# --------------------------------------------------------------------------- #


def test_router_call_matches_real_client_signature():
    """The kwargs the router sends must bind to OllamaClient.structured."""
    import inspect

    from hermes_assistant.llm.client import OllamaClient

    signature = inspect.signature(OllamaClient.structured)
    # Bind exactly what IntentRouter.classify passes. Raises TypeError if the
    # real client cannot accept it.
    signature.bind(
        OllamaClient,  # self
        "qwen3:4b",
        [{"role": "user", "content": "hi"}],
        IntentClassification,
        system="grounded system prompt",
        num_ctx=4096,
    )


def test_structured_prepends_system_prompt():
    """`system=` is delivered to Ollama as a leading system message."""
    from hermes_assistant.llm.client import OllamaClient

    captured: dict = {}

    class _StubClient(OllamaClient):
        def _post(self, path, payload, timeout):  # noqa: ANN001, ANN202
            captured["messages"] = payload["messages"]
            return {
                "message": {
                    "content": IntentClassification(
                        intent="smalltalk", params={}, confidence=0.9
                    ).model_dump_json()
                }
            }

    router = IntentRouter(_StubClient(), model="qwen3:4b")
    router.classify("Hello", ChatContext(project_id="proj1"))

    assert captured["messages"][0]["role"] == "system"
    assert "proj1" in captured["messages"][0]["content"]
    assert captured["messages"][-1] == {"role": "user", "content": "Hello"}
