"""Tests for the Microsoft 365 Copilot Retrieval and Chat clients.

Fully offline: the transport is a stub session, so nothing here needs a
tenant, a licence or a network. What is being pinned is the *contract* — the
request bodies Microsoft documents, the response shapes, and above all the
client-side guards that exist because the service's own failure modes are
quiet.

These clients have NOT been run against a live tenant. Everything below
checks the documented contract, which is a different and weaker claim than
"it works". Treat a green suite here as "we send what the docs say", not as
integration proof.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from hermes_assistant.m365.auth import scopes_for
from hermes_assistant.m365.client import (
    CopilotAPIError,
    CopilotClient,
    CopilotThrottledError,
)
from hermes_assistant.m365.models import MAX_QUERY_CHARS, MAX_RESULTS, RetrievalHit


class _Resp:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status: int, payload: Any = None, headers: dict | None = None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self.content = b"" if payload is None else json.dumps(payload).encode()
        self.text = self.content.decode()

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _Session:
    """Records the last request and replays queued responses."""

    def __init__(self, *responses: _Resp) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def post(self, url, json=None, headers=None, timeout=None):  # noqa: A002
        self.calls.append({"url": url, "json": json, "headers": headers})
        if not self._responses:
            raise AssertionError(f"unexpected extra POST to {url}")
        return self._responses.pop(0)


class _Auth:
    """Never touches MSAL or the network."""

    def __init__(self) -> None:
        self.requested_scopes: list[list[str]] = []

    def token(self, scopes, interactive=True):  # noqa: ANN001, ARG002
        self.requested_scopes.append(list(scopes))
        return "test-token"


def _client(*responses: _Resp) -> tuple[CopilotClient, _Session, _Auth]:
    session, auth = _Session(*responses), _Auth()
    return CopilotClient(auth=auth, session=session), session, auth


_HIT = {
    "retrievalHits": [
        {
            "webUrl": "https://contoso.sharepoint.com/sites/P/Protokoll.docx",
            "resourceType": "listItem",
            "resourceMetadata": {"title": "Sitzungsprotokoll", "author": "A. Muster"},
            "extracts": [
                {"text": "Abnahme bis 30.09.", "relevanceScore": 0.87, "pageNumbers": [2]}
            ],
            "sensitivityLabel": {"displayName": "Intern", "priority": 1},
        }
    ]
}


# --------------------------------------------------------------------------- #
# Retrieval — the request we send
# --------------------------------------------------------------------------- #


def test_retrieval_posts_to_the_documented_endpoint() -> None:
    client, session, _ = _client(_Resp(200, _HIT))
    client.retrieve("Wann ist die Abnahme?")
    assert session.calls[0]["url"] == (
        "https://graph.microsoft.com/beta/copilot/retrieval"
    )


def test_retrieval_sends_the_documented_field_names() -> None:
    client, session, _ = _client(_Resp(200, _HIT))
    client.retrieve(
        "Wann ist die Abnahme?",
        data_source="sharePoint",
        filter_expression='path:"https://contoso.sharepoint.com/sites/P/"',
        resource_metadata=["title"],
        maximum_results=5,
    )
    body = session.calls[0]["json"]
    assert body["queryString"] == "Wann ist die Abnahme?"
    assert body["dataSource"] == "sharePoint"
    assert body["maximumNumberOfResults"] == 5
    assert body["filterExpression"].startswith("path:")
    assert body["resourceMetadata"] == ["title"]


def test_retrieval_omits_optional_fields_when_unset() -> None:
    """Sending an empty filterExpression is not the same as sending none."""
    client, session, _ = _client(_Resp(200, _HIT))
    client.retrieve("Frage")
    body = session.calls[0]["json"]
    assert "filterExpression" not in body
    assert "resourceMetadata" not in body


def test_retrieval_sends_a_bearer_token() -> None:
    client, session, _ = _client(_Resp(200, _HIT))
    client.retrieve("Frage")
    assert session.calls[0]["headers"]["Authorization"] == "Bearer test-token"


# --------------------------------------------------------------------------- #
# Retrieval — the limits, enforced before the round trip
# --------------------------------------------------------------------------- #


def test_a_query_over_the_character_limit_is_refused_locally() -> None:
    client, session, _ = _client()
    with pytest.raises(ValueError, match="1500"):
        client.retrieve("x" * (MAX_QUERY_CHARS + 1))
    assert session.calls == []


def test_a_query_at_exactly_the_limit_is_allowed() -> None:
    """Off-by-one here would reject a legal query for no reason."""
    client, _, _ = _client(_Resp(200, _HIT))
    client.retrieve("x" * MAX_QUERY_CHARS)


def test_more_than_25_results_is_refused_locally() -> None:
    client, session, _ = _client()
    with pytest.raises(ValueError, match="25"):
        client.retrieve("Frage", maximum_results=MAX_RESULTS + 1)
    assert session.calls == []


def test_zero_results_is_refused() -> None:
    client, _, _ = _client()
    with pytest.raises(ValueError):
        client.retrieve("Frage", maximum_results=0)


def test_an_empty_query_is_refused() -> None:
    client, _, _ = _client()
    with pytest.raises(ValueError):
        client.retrieve("   ")


def test_an_unknown_data_source_is_refused() -> None:
    """One source per call, and only the three the API accepts."""
    client, _, _ = _client()
    with pytest.raises(ValueError, match="sharePoint"):
        client.retrieve("Frage", data_source="everything")


def test_malformed_kql_is_refused_rather_than_silently_widening() -> None:
    """The documented failure mode is the dangerous one.

    "If the filterExpression request parameter has incorrect KQL syntax, the
    query successfully executes with no scoping" — so a typo does not error,
    it quietly searches the whole tenant and returns confident results from
    everywhere. An unbalanced quote is the easy version of that mistake.
    """
    client, session, _ = _client()
    with pytest.raises(ValueError, match="unbalanced quote"):
        client.retrieve("Frage", filter_expression='path:"https://host/sites/X/')
    assert session.calls == []


# --------------------------------------------------------------------------- #
# Retrieval — the response we parse
# --------------------------------------------------------------------------- #


def test_retrieval_parses_hits_and_extracts() -> None:
    client, _, _ = _client(_Resp(200, _HIT))
    result = client.retrieve("Frage")
    assert len(result.retrieval_hits) == 1
    hit = result.retrieval_hits[0]
    assert hit.title == "Sitzungsprotokoll"
    assert hit.extracts[0].relevance_score == 0.87
    assert hit.extracts[0].page_numbers == [2]


def test_retrieval_keeps_the_sensitivity_label() -> None:
    """The tenant's own classification is not ours to drop."""
    client, _, _ = _client(_Resp(200, _HIT))
    hit = client.retrieve("Frage").retrieval_hits[0]
    assert hit.sensitivity_label is not None
    assert hit.sensitivity_label.display_name == "Intern"


def test_extract_count_totals_across_documents() -> None:
    payload = {
        "retrievalHits": [
            {"webUrl": "a", "extracts": [{"text": "1"}, {"text": "2"}]},
            {"webUrl": "b", "extracts": [{"text": "3"}]},
        ]
    }
    client, _, _ = _client(_Resp(200, payload))
    assert client.retrieve("Frage").extract_count == 3


def test_an_unknown_response_field_does_not_break_parsing() -> None:
    """These are preview APIs; a new field must not take the dashboard down."""
    payload = {
        "retrievalHits": [{"webUrl": "a", "extracts": [], "somethingNew": 42}],
        "@odata.context": "https://graph.microsoft.com/beta/$metadata",
    }
    client, _, _ = _client(_Resp(200, payload))
    assert len(client.retrieve("Frage").retrieval_hits) == 1


def test_an_empty_result_set_is_not_an_error() -> None:
    client, _, _ = _client(_Resp(200, {"retrievalHits": []}))
    assert client.retrieve("Frage").retrieval_hits == []


def test_a_hit_without_a_title_falls_back_to_the_file_name() -> None:
    """resourceMetadata only carries what was asked for, so title can be absent."""
    hit = RetrievalHit.model_validate(
        {"webUrl": "https://host/sites/P/Ablaufplan.xlsx", "extracts": []}
    )
    assert hit.title == "Ablaufplan.xlsx"


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


def test_403_explains_the_two_usual_causes() -> None:
    client, _, _ = _client(_Resp(403, {"error": {"message": "Forbidden"}}))
    with pytest.raises(CopilotAPIError, match="consent|licence"):
        client.retrieve("Frage")


def test_429_surfaces_retry_after() -> None:
    client, _, _ = _client(_Resp(429, None, {"Retry-After": "30"}))
    with pytest.raises(CopilotThrottledError) as excinfo:
        client.retrieve("Frage")
    assert excinfo.value.retry_after == 30.0


def test_throttling_without_a_header_still_gives_a_delay() -> None:
    client, _, _ = _client(_Resp(503, None))
    with pytest.raises(CopilotThrottledError) as excinfo:
        client.retrieve("Frage")
    assert excinfo.value.retry_after > 0


def test_a_graph_error_message_reaches_the_caller() -> None:
    client, _, _ = _client(
        _Resp(400, {"error": {"message": "queryString is required"}})
    )
    with pytest.raises(CopilotAPIError, match="queryString is required"):
        client.retrieve("Frage")


# --------------------------------------------------------------------------- #
# Chat
# --------------------------------------------------------------------------- #

_CONVERSATION = {"id": "conv-1"}
_ANSWER = {
    "id": "conv-1",
    "turnCount": 1,
    "messages": [
        {"@odata.type": "#microsoft.graph.copilotUserMessage", "text": "Frage"},
        {
            "@odata.type": "#microsoft.graph.copilotResponseMessage",
            "text": "Die Abnahme ist am 30.09.",
            "attributions": [
                {
                    "attributionType": "file",
                    "providerDisplayName": "Protokoll.docx",
                    "seeMoreWebUrl": "https://contoso.sharepoint.com/x",
                }
            ],
        },
    ],
}


def test_chat_opens_a_conversation_then_posts_the_turn() -> None:
    client, session, _ = _client(_Resp(201, _CONVERSATION), _Resp(200, _ANSWER))
    client.chat("Frage")
    assert session.calls[0]["url"].endswith("/copilot/conversations")
    assert session.calls[1]["url"].endswith("/copilot/conversations/conv-1/chat")


def test_chat_reuses_a_conversation_when_given_one() -> None:
    """Continuing a thread must not cost an extra round trip."""
    client, session, _ = _client(_Resp(200, _ANSWER))
    client.chat("Zweite Frage", conversation_id="conv-9")
    assert len(session.calls) == 1
    assert session.calls[0]["url"].endswith("/copilot/conversations/conv-9/chat")


def test_chat_sends_the_documented_message_shape() -> None:
    client, session, _ = _client(_Resp(200, _ANSWER))
    client.chat("Frage", conversation_id="c", time_zone="W. Europe Standard Time")
    body = session.calls[0]["json"]
    assert body["message"]["text"] == "Frage"
    assert body["locationHint"]["timeZone"] == "W. Europe Standard Time"


def test_additional_context_is_wrapped_per_item() -> None:
    client, session, _ = _client(_Resp(200, _ANSWER))
    client.chat("Frage", conversation_id="c", additional_context=["A", "B"])
    assert session.calls[0]["json"]["additionalContext"] == [
        {"text": "A"},
        {"text": "B"},
    ]


def test_chat_returns_the_assistant_turn_not_the_prompt() -> None:
    """The response carries the whole thread, the user's own message included."""
    client, _, _ = _client(_Resp(200, _ANSWER))
    answer = client.chat("Frage", conversation_id="conv-1")
    assert answer.text == "Die Abnahme ist am 30.09."


def test_chat_keeps_the_attributions() -> None:
    """An unsourced summary of a project is not evidence."""
    client, _, _ = _client(_Resp(200, _ANSWER))
    answer = client.chat("Frage", conversation_id="conv-1")
    assert answer.attributions[0].provider_display_name == "Protokoll.docx"
    assert answer.attributions[0].see_more_web_url.endswith("/x")


def test_chat_carries_the_conversation_id_back_for_the_next_turn() -> None:
    client, _, _ = _client(_Resp(200, _ANSWER))
    assert client.chat("Frage", conversation_id="conv-1").conversation_id == "conv-1"


def test_an_empty_chat_message_is_refused() -> None:
    client, _, _ = _client()
    with pytest.raises(ValueError):
        client.chat("  ")


def test_a_conversation_without_an_id_is_an_error() -> None:
    client, _, _ = _client(_Resp(201, {}))
    with pytest.raises(CopilotAPIError, match="without an id"):
        client.chat("Frage")


# --------------------------------------------------------------------------- #
# Scopes
# --------------------------------------------------------------------------- #


def test_retrieval_asks_only_for_file_scopes() -> None:
    """Consent to read someone's mail is not collected to search SharePoint."""
    scopes = scopes_for(data_source="sharePoint")
    assert set(scopes) == {"Files.Read.All", "Sites.Read.All"}
    assert "Mail.Read" not in scopes


def test_querying_a_connector_adds_the_connector_scope() -> None:
    assert "ExternalItem.Read.All" in scopes_for(data_source="externalItem")


def test_chat_asks_for_the_wider_grounding_scopes() -> None:
    """Chat grounds across mail, chat and meetings, so it needs more."""
    scopes = scopes_for(chat=True)
    assert "Mail.Read" in scopes
    assert "ChannelMessage.Read.All" in scopes


def test_the_client_never_requests_an_interactive_sign_in() -> None:
    """A web request must not block on someone reading a device code."""

    class _Strict(_Auth):
        def token(self, scopes, interactive=True):  # noqa: ANN001
            assert interactive is False, "API path must not prompt"
            return "t"

    session = _Session(_Resp(200, _HIT))
    CopilotClient(auth=_Strict(), session=session).retrieve("Frage")


# --------------------------------------------------------------------------- #
# The off-by-default gate
#
# Every other part of HERMES runs on this machine (MASTER.md: "no programmatic
# M365 access, no credentials, nothing leaves the box"). These commands are the
# single exception, so the switch that enables them is worth a test of its own:
# credentials sitting in the environment must not be enough to start sending
# queries to Microsoft.
# --------------------------------------------------------------------------- #


def test_the_m365_integration_is_off_by_default() -> None:
    from hermes_assistant.config import Settings

    assert Settings().m365_enabled is False


@pytest.mark.parametrize("command", ["m365-retrieve", "m365-chat", "m365-login"])
def test_the_commands_refuse_while_the_integration_is_off(command: str) -> None:
    from typer.testing import CliRunner

    from hermes_assistant.cli import app as cli_app

    runner = CliRunner()
    args = [command] + ([] if command == "m365-login" else ["Frage"])
    result = runner.invoke(cli_app, args)

    assert result.exit_code == 2
    assert "integration is off" in result.output


def test_credentials_alone_do_not_enable_it(monkeypatch) -> None:
    """Having a tenant and client id configured is not consent to use them."""
    from typer.testing import CliRunner

    import hermes_assistant.cli as cli_module

    monkeypatch.setattr(cli_module.settings, "m365_tenant_id", "tenant", raising=False)
    monkeypatch.setattr(cli_module.settings, "m365_client_id", "client", raising=False)
    monkeypatch.setattr(cli_module.settings, "m365_enabled", False, raising=False)

    result = CliRunner().invoke(cli_module.app, ["m365-retrieve", "Frage"])

    assert result.exit_code == 2


def test_an_unconfigured_login_names_what_is_missing(tmp_path) -> None:
    """The failure has to be actionable, not just "auth error"."""
    from hermes_assistant.m365.auth import DeviceCodeAuth, M365NotConfiguredError

    auth = DeviceCodeAuth(tenant_id="", client_id="", cache_path=tmp_path / "c.json")
    with pytest.raises(M365NotConfiguredError, match="HERMES_M365_TENANT_ID"):
        auth.token(["Files.Read.All"])


def test_the_token_cache_is_not_world_readable(tmp_path) -> None:
    """It holds refresh tokens — credentials, not data."""
    import stat
    import types

    from hermes_assistant.m365.auth import DeviceCodeAuth

    cache_file = tmp_path / "m365_token_cache.json"
    auth = DeviceCodeAuth(tenant_id="t", client_id="c", cache_path=cache_file)

    fake_cache = types.SimpleNamespace(
        has_state_changed=True, serialize=lambda: '{"secret": "refresh-token"}'
    )
    auth._save_cache(types.SimpleNamespace(token_cache=fake_cache))

    mode = stat.S_IMODE(cache_file.stat().st_mode)
    assert mode == 0o600, f"token cache is mode {mode:o}"


def test_sign_out_removes_the_cache(tmp_path) -> None:
    from hermes_assistant.m365.auth import DeviceCodeAuth

    cache_file = tmp_path / "cache.json"
    cache_file.write_text("{}", encoding="utf-8")
    auth = DeviceCodeAuth(tenant_id="t", client_id="c", cache_path=cache_file)

    assert auth.sign_out() is True
    assert not cache_file.exists()
    assert auth.sign_out() is False
