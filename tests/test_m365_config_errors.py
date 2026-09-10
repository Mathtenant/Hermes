"""Tests for what happens when the M365 integration is misconfigured.

Every one of these started as a real failure on a real machine. A placeholder
copied straight out of the setup instructions reached MSAL as if it were a
tenant, and the person got a forty-line traceback ending in "double check your
tenant name or GUID is correct" — accurate, and not what they needed to be
told. The instruction printed alongside it was wrong as well.

What is pinned here is that each way of getting it wrong produces one readable
sentence naming the variable at fault, and that no advice is printed that would
not fix the thing it is printed for.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import patch

import pytest
import typer

from hermes_assistant.m365.auth import (
    DeviceCodeAuth,
    M365AuthError,
    M365NotConfiguredError,
)

_GOOD_GUID = "11111111-2222-3333-4444-555555555555"
_OTHER_GUID = "99999999-8888-7777-6666-555555555555"


def _auth(tenant: str, client: str = _GOOD_GUID) -> DeviceCodeAuth:
    return DeviceCodeAuth(tenant_id=tenant, client_id=client)


# --------------------------------------------------------------------------- #
# Placeholders
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "value",
    [
        "<deine-Verzeichnis-ID>",      # the one that actually happened
        "<your-tenant-id>",
        "{tenant}",
        "[tenant]",
        "your_tenant",
        "changeme",
        " 11111111-2222-3333-4444-555555555555 ",   # pasted with whitespace
    ],
)
def test_a_placeholder_is_refused_before_microsoft_is_contacted(value: str) -> None:
    with pytest.raises(M365NotConfiguredError) as exc:
        _auth(value)._require_config()
    assert "placeholder" in str(exc.value).lower()
    assert "HERMES_M365_TENANT_ID" in str(exc.value)


def test_the_offending_value_is_quoted_back() -> None:
    """"One of your ids is wrong" sends somebody to check both."""
    with pytest.raises(M365NotConfiguredError) as exc:
        _auth("<deine-Verzeichnis-ID>")._require_config()
    assert "<deine-Verzeichnis-ID>" in str(exc.value)


# --------------------------------------------------------------------------- #
# Shape
# --------------------------------------------------------------------------- #


def test_a_missing_value_is_still_reported() -> None:
    with pytest.raises(M365NotConfiguredError):
        _auth("", _GOOD_GUID)._require_config()
    with pytest.raises(M365NotConfiguredError):
        _auth(_GOOD_GUID, "")._require_config()


def test_a_client_id_must_be_a_guid() -> None:
    """The two ids are easy to swap, and only one of them may be a domain."""
    with pytest.raises(M365NotConfiguredError) as exc:
        _auth(_GOOD_GUID, "contoso.onmicrosoft.com")._require_config()
    assert "CLIENT_ID" in str(exc.value)
    assert "Application (client) ID" in str(exc.value)


def test_a_tenant_may_be_a_guid_or_a_domain() -> None:
    _auth(_GOOD_GUID)._require_config()
    _auth("contoso.onmicrosoft.com")._require_config()
    _auth("contoso.com")._require_config()


def test_a_bare_word_is_not_a_tenant() -> None:
    with pytest.raises(M365NotConfiguredError) as exc:
        _auth("contoso")._require_config()
    assert "neither a GUID nor a domain" in str(exc.value)


def test_every_config_error_says_where_to_put_the_values() -> None:
    """A message that only says what is wrong leaves the reader hunting."""
    for tenant, client in (
        ("", _GOOD_GUID),
        ("<placeholder>", _GOOD_GUID),
        ("contoso", _GOOD_GUID),
        (_GOOD_GUID, "nope"),
    ):
        with pytest.raises(M365NotConfiguredError) as exc:
            _auth(tenant, client)._require_config()
        assert ".env" in str(exc.value)


# --------------------------------------------------------------------------- #
# MSAL's own failures
# --------------------------------------------------------------------------- #


def test_a_tenant_microsoft_cannot_resolve_is_an_error_not_a_traceback() -> None:
    """Well-formed but wrong, a blocked proxy, or simply offline: MSAL raises
    ValueError, which the CLI does not catch.

    msal is stubbed into sys.modules rather than imported: it is an optional
    extra, absent on any machine that has not turned the integration on — and
    `importorskip` would make this test vanish on exactly those machines,
    while the code path it covers is the one they hit.
    """
    fake = types.ModuleType("msal")
    fake.SerializableTokenCache = lambda: types.SimpleNamespace(
        deserialize=lambda _: None
    )

    def _boom(*_a, **_kw):
        raise ValueError("Unable to get authority configuration")

    fake.PublicClientApplication = _boom

    with patch.dict(sys.modules, {"msal": fake}):
        with pytest.raises(M365AuthError) as exc:
            _auth(_OTHER_GUID)._build_app()
    assert "could not resolve tenant" in str(exc.value)
    assert _OTHER_GUID in str(exc.value)
    assert not isinstance(exc.value, M365NotConfiguredError)


# --------------------------------------------------------------------------- #
# The printed advice
# --------------------------------------------------------------------------- #


def test_the_extra_survives_rich_markup() -> None:
    """Rich reads `[m365]` as a style tag and drops it, which turned the fix
    into `pip install -e "."` — the one command that would not fix it.

    Rendered through a real Console, not asserted against the source string:
    the bug was in the rendering, so that is where the test has to look.
    """
    import io

    from rich.console import Console

    from hermes_assistant import cli

    buf = io.StringIO()
    with patch.object(cli, "console", Console(file=buf, width=100, no_color=True)), \
         patch.object(cli.settings, "m365_enabled", False):
        with pytest.raises(typer.Exit):
            cli._require_m365()
    out = buf.getvalue()
    assert 'pip install -e ".[m365]"' in out
    assert 'pip install -e "."' not in out


def test_the_guard_names_all_four_preconditions() -> None:
    """Naming three sent people into the next failure one at a time."""
    import io

    from rich.console import Console

    from hermes_assistant import cli

    buf = io.StringIO()
    with patch.object(cli, "console", Console(file=buf, width=100, no_color=True)), \
         patch.object(cli.settings, "m365_enabled", False):
        with pytest.raises(typer.Exit):
            cli._require_m365()
    out = buf.getvalue()
    for token in ("m365]", "HERMES_M365_ENABLED", "HERMES_M365_TENANT_ID",
                  "HERMES_M365_CLIENT_ID"):
        assert token in out
