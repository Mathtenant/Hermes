"""Tests for POST /api/todos/parse — one sentence into the create form's fields.

The endpoint is a shortcut, never a dependency: it fills a dialog the person
then reads and submits. So what these tests protect is not "the model is
clever" but the two things that hold whatever the model says:

* an unreachable model degrades to a message you can act on, not a 500, and
* nothing the model returns reaches the database unchecked. It is a small
  local model doing best-effort extraction on a hurried sentence — it can
  answer with a 400-character title, a priority it invented, or the words
  "nächsten Freitag" in a field documented as YYYY-MM-DD.

The model itself is stubbed throughout. A test that needs Ollama running is a
test that silently stops running.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from hermes_assistant.llm.client import OllamaConnectionError
from hermes_assistant.webapp.server import _ParsedTodo, app

client = TestClient(app, raise_server_exceptions=False)


def _answer(**fields):
    """Patch the model to answer with one _ParsedTodo."""
    defaults = {"title": "Etwas tun", "owner": "", "priority": "medium", "due_date": ""}
    return patch(
        "hermes_assistant.llm.client.OllamaClient.structured",
        return_value=_ParsedTodo(**{**defaults, **fields}),
    )


def _parse(text: str = "irgendwas"):
    return client.post("/api/todos/parse", json={"text": text})


# --------------------------------------------------------------------------- #
# The happy path
# --------------------------------------------------------------------------- #


def test_a_sentence_becomes_the_forms_fields():
    with _answer(
        title="Rechnung Lieferant X prüfen",
        owner="Controlling",
        priority="blocker",
        due_date="2026-09-11",
    ):
        r = _parse("Rechnung Lieferant X bis Freitag prüfen, Controlling, dringend")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Rechnung Lieferant X prüfen"
    assert body["owner"] == "Controlling"
    assert body["priority"] == "blocker"
    assert body["due_date"] == "2026-09-11"


def test_the_answering_model_is_named():
    """Worth knowing which model read the sentence, when it read it badly."""
    with _answer():
        assert _parse().json()["model"]


def test_the_prompt_carries_todays_date_and_weekday():
    """"bis Freitag" is unanswerable without knowing which day today is, and
    models are markedly worse at deriving the weekday from a date than at
    being told it."""
    with patch(
        "hermes_assistant.llm.client.OllamaClient.structured",
        return_value=_ParsedTodo(title="x"),
    ) as spy:
        _parse("bis Freitag")
    prompt = spy.call_args.args[1][0]["content"]
    assert date.today().isoformat() in prompt
    weekday = ("Montag", "Dienstag", "Mittwoch", "Donnerstag",
               "Freitag", "Samstag", "Sonntag")[date.today().weekday()]
    assert weekday in prompt


def test_nothing_is_created():
    """It fills the dialog. The person presses Anlegen."""
    with _answer(title="Nicht anlegen bitte"):
        _parse()
    listed = client.get("/api/dashboard")
    assert "Nicht anlegen bitte" not in listed.text


# --------------------------------------------------------------------------- #
# The model is untrusted
# --------------------------------------------------------------------------- #


def test_an_invented_priority_falls_back_to_medium():
    with _answer(priority="sehr wichtig!!"):
        assert _parse().json()["priority"] == "medium"


@pytest.mark.parametrize(
    "bad",
    ["nächsten Freitag", "11.09.2026", "2026-9-11", "morgen", "2026-13-01",
     "2026-02-31", "irgendwann"],
)
def test_a_date_that_is_not_a_date_is_dropped(bad: str):
    """A well-formed impossible date (2026-02-31) matches the pattern and is
    still no date; the create endpoint would 422 on it with nothing the
    person could act on."""
    with _answer(due_date=bad):
        assert _parse().json()["due_date"] == ""


def test_an_overlong_title_is_cut_not_rejected():
    with _answer(title="x" * 900):
        body = _parse().json()
    assert 0 < len(body["title"]) <= 200


def test_an_overlong_owner_is_cut():
    with _answer(owner="y" * 500):
        assert len(_parse().json()["owner"]) <= 80


def test_a_model_answer_is_redacted_like_anything_else_typed_in():
    """Hand-entered text goes through the importer's redaction. A model
    echoing an address out of the sentence must not skip it — it is the same
    text on the same dashboard."""
    with _answer(title="Rückruf an a.muster@example.com"):
        assert "a.muster@example.com" not in _parse().json()["title"]


# --------------------------------------------------------------------------- #
# When the model is not there
# --------------------------------------------------------------------------- #


def test_an_unreachable_model_is_a_503_with_a_way_forward():
    """503, not 500: the service is fine, the model is not reachable — and
    the person can still fill the form in by hand."""
    with patch(
        "hermes_assistant.llm.client.OllamaClient.structured",
        side_effect=OllamaConnectionError("Cannot reach Ollama at http://x/api/chat"),
    ):
        r = _parse()
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "von Hand" in detail
    assert "ollama serve" in detail
    assert "OllamaConnectionError" in detail   # the cause, not just the advice


def test_empty_text_is_rejected_before_the_model_is_bothered():
    with patch("hermes_assistant.llm.client.OllamaClient.structured") as spy:
        r = client.post("/api/todos/parse", json={"text": "   "})
    assert r.status_code == 422
    assert not spy.called


def test_a_novel_length_sentence_is_rejected():
    with patch("hermes_assistant.llm.client.OllamaClient.structured") as spy:
        r = client.post("/api/todos/parse", json={"text": "x" * 5000})
    assert r.status_code == 422
    assert not spy.called
