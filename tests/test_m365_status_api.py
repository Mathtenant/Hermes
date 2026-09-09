"""Tests for the Copilot POC page's two endpoints.

The integration needs an app registration, admin-granted permissions, two
environment variables, an optional dependency and a signed-in person — and any
of the five can be the reason nothing works. These endpoints answer "where
exactly am I stuck" without anyone reading source, so what they must never do
is answer it wrongly, or answer it by phoning Microsoft on page load.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from hermes_assistant.webapp.server import app

client = TestClient(app, raise_server_exceptions=False)

_CHECK_IDS = {"enabled", "tenant", "client", "msal", "token"}


def _status() -> dict:
    resp = client.get("/api/m365/status")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _by_id(body: dict) -> dict[str, dict]:
    return {c["id"]: c for c in body["checks"]}


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #


def test_every_precondition_is_reported() -> None:
    assert set(_by_id(_status())) == _CHECK_IDS


def test_each_failing_check_says_what_to_do_about_it() -> None:
    """A checklist of red rows with no remedy is a worse experience than no
    checklist: it tells somebody they are stuck without telling them how to
    stop being stuck."""
    for check in _status()["checks"]:
        assert check["fix"].strip(), check


def test_ready_is_true_only_when_every_check_passes() -> None:
    body = _status()
    assert body["ready"] == all(c["ok"] for c in body["checks"])


def test_the_switch_is_read_live(tmp_path: Path) -> None:
    with patch("hermes_assistant.webapp.server.settings.m365_enabled", True):
        assert _by_id(_status())["enabled"]["ok"] is True
    with patch("hermes_assistant.webapp.server.settings.m365_enabled", False):
        assert _by_id(_status())["enabled"]["ok"] is False


def test_the_tenant_id_itself_is_never_echoed() -> None:
    """It identifies the organisation, and this response is rendered in a
    browser and pasted into bug reports. Whether it is SET is the useful fact;
    what it is, is not."""
    secret = "11111111-2222-3333-4444-555555555555"
    with patch("hermes_assistant.webapp.server.settings.m365_tenant_id", secret):
        body = _status()
        assert _by_id(body)["tenant"]["ok"] is True
        assert secret not in str(body)


def test_the_client_id_is_not_echoed_either() -> None:
    secret = "99999999-8888-7777-6666-555555555555"
    with patch("hermes_assistant.webapp.server.settings.m365_client_id", secret):
        assert secret not in str(_status())


def test_the_documented_service_limits_are_reported() -> None:
    """The page states them as fact, so they must come from the module that
    enforces them rather than being retyped into a template."""
    from hermes_assistant.m365.models import (
        DATA_SOURCES,
        MAX_QUERY_CHARS,
        MAX_RESULTS,
    )

    limits = _status()["limits"]
    assert limits["max_query_chars"] == MAX_QUERY_CHARS
    assert limits["max_results"] == MAX_RESULTS
    assert limits["data_sources"] == list(DATA_SOURCES)


def test_the_scopes_are_reported_from_the_auth_module() -> None:
    from hermes_assistant.m365.auth import CHAT_SCOPES, RETRIEVAL_SCOPES

    scopes = _status()["scopes"]
    assert scopes["retrieval"] == list(RETRIEVAL_SCOPES)
    assert scopes["chat"] == list(CHAT_SCOPES)


def test_the_six_prompts_are_listed() -> None:
    """The prompt path is the one that works today; a page about the Copilot
    interface that only documented the unfinished half would mislead."""
    files = {p["file"] for p in _status()["prompts"]}
    assert len(files) == 6
    assert all(f.startswith("copilot_") and f.endswith(".txt") for f in files)
    assert all(p["bytes"] > 0 for p in _status()["prompts"])


def test_status_contacts_nobody() -> None:
    """It is fetched on page load. A page that reaches out to Microsoft to
    render itself would be slow when the tenant is unreachable and wrong on a
    machine with no network — and this one is offline by default."""
    with patch("requests.post") as post, patch("requests.get") as get:
        _status()
    assert not post.called
    assert not get.called


# --------------------------------------------------------------------------- #
# Probe
# --------------------------------------------------------------------------- #


def _probe() -> dict:
    resp = client.post("/api/m365/probe")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_the_probe_refuses_before_the_preconditions_are_met() -> None:
    with patch("hermes_assistant.webapp.server.settings.m365_enabled", False):
        body = _probe()
    assert body["ok"] is False
    assert body["stage"] == "preconditions"
    assert "enabled" in body["missing"]


def test_an_unconfigured_probe_contacts_nobody() -> None:
    with patch("hermes_assistant.webapp.server.settings.m365_enabled", False), \
         patch("requests.post") as post:
        _probe()
    assert not post.called


def _all_green():
    """Patch the five preconditions true without touching the network."""
    return patch(
        "hermes_assistant.webapp.server._m365_checks",
        return_value=[{"id": i, "label": i, "ok": True, "detail": "", "fix": ""}
                      for i in sorted(_CHECK_IDS)],
    )


def test_the_probe_never_starts_an_interactive_sign_in() -> None:
    """A device code blocks until somebody types it on another device. A web
    request that waits on that holds a worker until it times out, so an
    unsigned-in state is REPORTED, not resolved here.
    """
    with _all_green(), patch(
        "hermes_assistant.m365.auth.DeviceCodeAuth.token", return_value="tok"
    ) as token, patch(
        "hermes_assistant.m365.client.CopilotClient.retrieve"
    ) as retrieve:
        retrieve.return_value = type(
            "R", (), {"retrieval_hits": [], "extract_count": 0}
        )()
        _probe()
    assert token.call_args.kwargs.get("interactive") is False


def test_a_sign_in_failure_is_reported_with_the_command_that_fixes_it() -> None:
    from hermes_assistant.m365.auth import M365AuthError

    with _all_green(), patch(
        "hermes_assistant.m365.auth.DeviceCodeAuth.token",
        side_effect=M365AuthError("no cached account"),
    ):
        body = _probe()
    assert body["ok"] is False
    assert body["stage"] == "auth"
    assert "m365-login" in body["fix"]


def test_an_api_error_is_reported_with_its_status() -> None:
    from hermes_assistant.m365.client import CopilotAPIError

    with _all_green(), patch(
        "hermes_assistant.m365.auth.DeviceCodeAuth.token", return_value="tok"
    ), patch(
        "hermes_assistant.m365.client.CopilotClient.retrieve",
        side_effect=CopilotAPIError("Forbidden", status=403),
    ):
        body = _probe()
    assert body["ok"] is False
    assert body["stage"] == "retrieval"
    assert body["status"] == 403


def test_a_successful_probe_reports_counts_not_content() -> None:
    """"Does the pipe work" is the question. A POC page is not the place to
    render tenant document extracts into a browser."""
    hit = type("H", (), {"title": "Projektstatus.docx"})()
    result = type("R", (), {"retrieval_hits": [hit], "extract_count": 4})()
    with _all_green(), patch(
        "hermes_assistant.m365.auth.DeviceCodeAuth.token", return_value="tok"
    ), patch(
        "hermes_assistant.m365.client.CopilotClient.retrieve", return_value=result
    ):
        body = _probe()
    # Exact equality, so a field added later has to be considered rather than
    # slipping tenant text into the response unnoticed.
    assert body == {
        "ok": True, "stage": "retrieval", "hits": 1, "extracts": 4,
        "titles": ["Projektstatus.docx"],
    }


def test_the_probe_asks_for_a_handful_not_the_maximum() -> None:
    """25 results to answer "is it reachable" is somebody else's rate limit
    spent on nothing."""
    result = type("R", (), {"retrieval_hits": [], "extract_count": 0})()
    with _all_green(), patch(
        "hermes_assistant.m365.auth.DeviceCodeAuth.token", return_value="tok"
    ), patch(
        "hermes_assistant.m365.client.CopilotClient.retrieve", return_value=result
    ) as retrieve:
        _probe()
    assert retrieve.call_args.kwargs["maximum_results"] <= 5
