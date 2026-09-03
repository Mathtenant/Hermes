"""Delegated sign-in for the Copilot APIs, via device code.

**Delegated only, by force of the API.** Microsoft does not support
application permissions on the Retrieval API: there is no daemon/service
identity that can read tenant content this way. Every call is made *as a
signed-in person*, and the results are trimmed to what that person may
already see. That is a feature for this project rather than a limitation —
HERMES cannot be used to widen anyone's access — but it does mean there is no
unattended mode, and a token has to be refreshed by a human eventually.

Device code rather than an interactive redirect: HERMES is a local tool with
no public redirect URI and no guarantee of a browser on the same machine, and
the device-code flow needs neither. The user gets a short code, types it into
microsoft.com/devicelogin on any device, and the token lands here.

Tokens are cached on disk so a POC session does not re-prompt on every call.
The cache holds refresh tokens — credentials, not data — so it is written
0600 and lives under the data directory, never in the repository.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from hermes_assistant.config import settings

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com"

# Scopes the two APIs need, as documented. Retrieval needs the first two (plus
# ExternalItem.Read.All only when querying connectors); Chat asks for the full
# set because it grounds across mail, chat and meetings as well as files.
#
# Requesting the union up front keeps the POC to a single consent prompt. A
# production build should ask only for what the feature in hand uses — consent
# to read someone's mail is not a thing to collect casually.
RETRIEVAL_SCOPES = ("Files.Read.All", "Sites.Read.All")
CONNECTOR_SCOPES = ("ExternalItem.Read.All",)
CHAT_SCOPES = (
    "Sites.Read.All",
    "Mail.Read",
    "People.Read.All",
    "OnlineMeetingTranscript.Read.All",
    "Chat.Read",
    "ChannelMessage.Read.All",
    "ExternalItem.Read.All",
)


class M365AuthError(RuntimeError):
    """Sign-in could not be completed."""


class M365NotConfiguredError(M365AuthError):
    """No tenant/client id — the integration was never switched on."""


def _token_cache_path() -> Path:
    return Path(settings.data_dir) / "m365_token_cache.json"


def scopes_for(data_source: str | None = None, *, chat: bool = False) -> list[str]:
    """The scope set a given call needs.

    Kept as a function rather than a constant so the connector scope is only
    requested when a connector is actually being queried.
    """
    if chat:
        return list(CHAT_SCOPES)
    scopes = list(RETRIEVAL_SCOPES)
    if data_source == "externalItem":
        scopes += list(CONNECTOR_SCOPES)
    return scopes


class DeviceCodeAuth:
    """Acquire and cache a delegated Graph token.

    MSAL is imported lazily inside the methods: it is an optional extra, and
    importing this module must not fail on a machine that never turns the
    integration on.
    """

    def __init__(
        self,
        tenant_id: str | None = None,
        client_id: str | None = None,
        cache_path: Path | None = None,
    ) -> None:
        self.tenant_id = tenant_id or getattr(settings, "m365_tenant_id", "")
        self.client_id = client_id or getattr(settings, "m365_client_id", "")
        self.cache_path = cache_path or _token_cache_path()

    # ------------------------------------------------------------------ #
    def _require_config(self) -> None:
        if not self.tenant_id or not self.client_id:
            raise M365NotConfiguredError(
                "M365 integration is not configured. Set HERMES_M365_TENANT_ID and "
                "HERMES_M365_CLIENT_ID (an Entra app registration with the delegated "
                "Graph scopes, 'Allow public client flows' enabled), then run "
                "`hermes m365-login`."
            )

    def _build_app(self) -> Any:
        try:
            import msal
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise M365AuthError(
                "The msal package is required for the M365 integration. "
                "Install it with: pip install -e '.[m365]'"
            ) from exc

        cache = msal.SerializableTokenCache()
        if self.cache_path.exists():
            try:
                cache.deserialize(self.cache_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                # A corrupt cache is not worth failing a login over — the user
                # simply signs in again and it is overwritten.
                logger.warning("Ignoring unreadable token cache at %s", self.cache_path)

        return msal.PublicClientApplication(
            self.client_id,
            authority=f"https://login.microsoftonline.com/{self.tenant_id}",
            token_cache=cache,
        )

    def _save_cache(self, app: Any) -> None:
        cache = app.token_cache
        if not getattr(cache, "has_state_changed", False):
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        # Write then chmod, and chmod before the secret is useful to anyone:
        # create the file empty with the right mode first.
        fd = os.open(self.cache_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(cache.serialize())

    # ------------------------------------------------------------------ #
    def token(self, scopes: list[str], *, interactive: bool = True) -> str:
        """Return a bearer token, signing in only if the cache cannot serve it.

        ``interactive=False`` makes this raise instead of printing a device
        code — used by the API path, where blocking a web request on somebody
        reading a code off a terminal would hang the request.
        """
        self._require_config()
        app = self._build_app()

        accounts = app.get_accounts()
        if accounts:
            result = app.acquire_token_silent(scopes, account=accounts[0])
            if result and "access_token" in result:
                self._save_cache(app)
                return str(result["access_token"])

        if not interactive:
            raise M365AuthError(
                "Not signed in to Microsoft 365 (or the cached token expired). "
                "Run `hermes m365-login` first."
            )

        flow = app.initiate_device_flow(scopes=scopes)
        if "user_code" not in flow:
            raise M365AuthError(
                "Could not start device sign-in: "
                f"{flow.get('error_description') or flow.get('error') or flow}"
            )
        # The message is Microsoft's, and it carries the code and the URL.
        print(flow["message"], flush=True)

        result = app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise M365AuthError(
                "Sign-in failed: "
                f"{result.get('error_description') or result.get('error')}"
            )
        self._save_cache(app)
        return str(result["access_token"])

    def sign_out(self) -> bool:
        """Forget the cached tokens. Returns True if there was a cache to remove."""
        if not self.cache_path.exists():
            return False
        self.cache_path.unlink()
        return True
