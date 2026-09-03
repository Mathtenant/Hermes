"""HTTP client for the Copilot Retrieval and Chat APIs.

Both live under Microsoft Graph and share auth, error handling and throttling
behaviour, so they share a client rather than getting one each.

The service limits are enforced *here*, before the request goes out. A
1,501-character query and a `maximumNumberOfResults` of 26 are both rejectable
without a round trip, and a precise local error ("query is 1620 characters,
the limit is 1500") is worth more to the caller than a generic 400 half a
second later.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from hermes_assistant.m365.auth import GRAPH_BASE, DeviceCodeAuth, scopes_for
from hermes_assistant.m365.models import (
    DATA_SOURCES,
    MAX_QUERY_CHARS,
    MAX_RESULTS,
    ChatAnswer,
    ChatAttribution,
    RetrievalResult,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60


class CopilotAPIError(RuntimeError):
    """The service refused or failed the request."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class CopilotThrottledError(CopilotAPIError):
    """429/503 with the service asking us to back off."""

    def __init__(self, message: str, *, retry_after: float, status: int) -> None:
        super().__init__(message, status=status)
        self.retry_after = retry_after


class CopilotClient:
    """Talks to ``/copilot/retrieval`` and ``/copilot/conversations``.

    ``api_version`` defaults to beta: at the time of writing the Chat API is
    beta-only, and pinning one version for both keeps a POC from silently
    mixing contracts. Move retrieval to v1.0 deliberately, not by accident.
    """

    def __init__(
        self,
        auth: DeviceCodeAuth | None = None,
        api_version: str = "beta",
        session: requests.Session | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.auth = auth or DeviceCodeAuth()
        self.api_version = api_version
        self.session = session or requests.Session()
        self.timeout = timeout

    # ------------------------------------------------------------------ #
    def _url(self, path: str) -> str:
        return f"{GRAPH_BASE}/{self.api_version}{path}"

    def _post(
        self, path: str, payload: dict[str, Any], scopes: list[str]
    ) -> dict[str, Any]:
        token = self.auth.token(scopes, interactive=False)
        url = self._url(path)
        start = time.perf_counter()
        try:
            resp = self.session.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise CopilotAPIError(f"Timed out calling {path}") from exc
        except requests.RequestException as exc:
            raise CopilotAPIError(f"Cannot reach Microsoft Graph: {exc}") from exc

        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info("%s → %s in %.0f ms", path, resp.status_code, elapsed_ms)

        if resp.status_code in (429, 503):
            # Honour Retry-After rather than guessing; Graph means it.
            raise CopilotThrottledError(
                f"Microsoft Graph is throttling ({resp.status_code}).",
                retry_after=float(resp.headers.get("Retry-After", "10") or 10),
                status=resp.status_code,
            )
        if resp.status_code == 403:
            raise CopilotAPIError(
                "Forbidden (403). Usually a missing admin consent for one of the "
                "delegated scopes, or no Microsoft 365 Copilot licence on this "
                "account.",
                status=403,
            )
        if resp.status_code >= 400:
            raise CopilotAPIError(
                f"{resp.status_code} from {path}: {_error_detail(resp)}",
                status=resp.status_code,
            )

        if not resp.content:
            return {}
        try:
            return dict(resp.json())
        except ValueError as exc:
            raise CopilotAPIError(f"{path} returned non-JSON content") from exc

    # ------------------------------------------------------------------ #
    # Retrieval
    # ------------------------------------------------------------------ #
    def retrieve(
        self,
        query: str,
        *,
        data_source: str = "sharePoint",
        filter_expression: str | None = None,
        resource_metadata: list[str] | None = None,
        maximum_results: int = MAX_RESULTS,
    ) -> RetrievalResult:
        """Ask for permission-trimmed extracts matching ``query``.

        Microsoft does the chunking and the ranking, so nothing here builds or
        stores an index. What comes back is text the signed-in user could
        already open.

        Args:
            query: One natural-language sentence. Keyword soup scores worse
                than a sentence, and misspelled context words score worse
                still — the service is doing semantic matching, not grep.
            data_source: One of ``sharePoint``, ``oneDriveBusiness``,
                ``externalItem``. One per call: the API has no "all sources"
                mode, so covering several means several calls.
            filter_expression: KQL, typically ``path:"https://…/sites/X/"``.
                A malformed expression does NOT fail the call — the service
                runs it unscoped instead, quietly returning the whole tenant.
                Hence the syntax check below: silently searching far more than
                you asked is the worst of the failure modes.
            resource_metadata: Extra fields to return per hit (e.g. ``title``,
                ``author``). Only what is asked for comes back.
            maximum_results: 1–25.
        """
        query = (query or "").strip()
        if not query:
            raise ValueError("query must not be empty")
        if len(query) > MAX_QUERY_CHARS:
            raise ValueError(
                f"query is {len(query)} characters; the Retrieval API limit is "
                f"{MAX_QUERY_CHARS}. Shorten it or split the search."
            )
        if data_source not in DATA_SOURCES:
            raise ValueError(
                f"data_source must be one of {', '.join(DATA_SOURCES)}; "
                f"got {data_source!r}"
            )
        if not 1 <= maximum_results <= MAX_RESULTS:
            raise ValueError(
                f"maximum_results must be between 1 and {MAX_RESULTS}; "
                f"got {maximum_results}"
            )
        if filter_expression:
            _check_kql(filter_expression)

        payload: dict[str, Any] = {
            "queryString": query,
            "dataSource": data_source,
            "maximumNumberOfResults": maximum_results,
        }
        if filter_expression:
            payload["filterExpression"] = filter_expression
        if resource_metadata:
            payload["resourceMetadata"] = resource_metadata

        data = self._post(
            "/copilot/retrieval", payload, scopes_for(data_source=data_source)
        )
        return RetrievalResult.model_validate(data)

    # ------------------------------------------------------------------ #
    # Chat
    # ------------------------------------------------------------------ #
    def start_conversation(self) -> str:
        """Open a conversation and return its id."""
        data = self._post("/copilot/conversations", {}, scopes_for(chat=True))
        conversation_id = data.get("id")
        if not isinstance(conversation_id, str) or not conversation_id:
            raise CopilotAPIError("Conversation was created without an id")
        return conversation_id

    def chat(
        self,
        text: str,
        *,
        conversation_id: str | None = None,
        additional_context: list[str] | None = None,
        time_zone: str | None = None,
    ) -> ChatAnswer:
        """Send one turn and return Copilot's reply.

        Text answers only. The Chat API cannot create a file, send mail, run
        code, or start a long task — so this is the right tool for reading the
        tenant's state back out, and the wrong one for producing a deliverable.
        Document generation stays in the interactive Copilot UI.

        Passing ``conversation_id`` continues an existing thread; omitting it
        opens a new one, which costs an extra round trip.
        """
        text = (text or "").strip()
        if not text:
            raise ValueError("text must not be empty")

        if conversation_id is None:
            conversation_id = self.start_conversation()

        payload: dict[str, Any] = {"message": {"text": text}}
        if additional_context:
            payload["additionalContext"] = [{"text": c} for c in additional_context]
        if time_zone:
            payload["locationHint"] = {"timeZone": time_zone}

        data = self._post(
            f"/copilot/conversations/{conversation_id}/chat",
            payload,
            scopes_for(chat=True),
        )
        return _to_answer(data, conversation_id)


def _error_detail(resp: requests.Response) -> str:
    """Pull Graph's own message out of an error body, falling back to text."""
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:400]
    error = body.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(error or body)[:400]


def _check_kql(expression: str) -> None:
    """Reject a filter the service would silently ignore.

    Documented behaviour: "If the filterExpression request parameter has
    incorrect KQL syntax, the query successfully executes with no scoping."
    A typo therefore does not fail — it widens the search to the whole tenant
    and returns confident, wrong-looking results. This catches the one mistake
    that is both easy to make and invisible afterwards: unbalanced quotes.
    """
    if expression.count('"') % 2:
        raise ValueError(
            "filter_expression has an unbalanced quote. Malformed KQL is not "
            "rejected by the service — it is ignored, and the search silently "
            'widens to the whole tenant. Example: path:"https://host/sites/X/"'
        )


def _to_answer(data: dict[str, Any], conversation_id: str) -> ChatAnswer:
    """Flatten a conversation envelope down to the last assistant turn.

    The response carries the whole thread, user turns included. Callers want
    the answer, so pick the last message that has text and is not the prompt
    that was just sent.
    """
    messages = data.get("messages")
    if not isinstance(messages, list):
        messages = []

    text = ""
    attributions: list[ChatAttribution] = []
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        odata_type = str(message.get("@odata.type", ""))
        if "userMessage" in odata_type:
            continue
        candidate = message.get("text")
        if isinstance(candidate, str) and candidate.strip():
            text = candidate
            raw = message.get("attributions")
            if isinstance(raw, list):
                attributions = [
                    ChatAttribution.model_validate(a)
                    for a in raw
                    if isinstance(a, dict)
                ]
            break

    return ChatAnswer(
        conversation_id=str(data.get("id") or conversation_id),
        text=text,
        attributions=attributions,
        turn_count=data.get("turnCount"),
    )
