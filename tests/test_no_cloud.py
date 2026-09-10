"""Guard tests: no cloud LLM SDKs, no non-local endpoints in source."""

import ast
import re
from pathlib import Path

from hermes_assistant.llm.client import OllamaClient

SRC = Path(__file__).resolve().parents[1] / "src"

# Cloud reasoning SDKs that must never be imported.
FORBIDDEN_ROOTS = {
    "openai",
    "anthropic",
    "cohere",
    "replicate",
    "together",
    "mistralai",
    "google",  # google.generativeai / vertexai
    "vertexai",
    "boto3",  # AWS Bedrock
    "litellm",
    "groq",
}

# Loopback hosts allowed in source URLs.
_LOOPBACK = ("localhost", "127.0.0.1", "::1", "0.0.0.0")
_URL_RE = re.compile(r"https?://([^/\s\"')]+)")


def _imported_modules() -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    for py in SRC.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.extend((py, alias.name) for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.append((py, node.module))
    return found


def test_no_cloud_sdk_imports() -> None:
    """No source module imports a cloud LLM SDK."""
    offenders = [
        (str(py), mod)
        for py, mod in _imported_modules()
        if mod.split(".")[0] in FORBIDDEN_ROOTS
    ]
    assert not offenders, f"Cloud SDK imports found: {offenders}"


# The one sanctioned exception to "every URL is loopback".
#
# The Microsoft 365 Copilot integration necessarily names Microsoft's hosts,
# and it is opt-in and off by default (HERMES_M365_ENABLED). Narrowing the
# guard to this package — rather than relaxing the pattern, or deleting the
# test — keeps it doing its real job: no OTHER module can start talking to a
# cloud endpoint without this test failing. The exception is a named module,
# not a hole.
_M365_PKG = SRC / "hermes_assistant" / "m365"
_M365_HOSTS = {"graph.microsoft.com", "login.microsoftonline.com"}

# Placeholders in docstrings and help text — "https://host/sites/X/" and
# friends. They are documentation of the KQL a *user* types, not endpoints
# this code calls.
_DOC_PLACEHOLDERS = {"host", "…", "contoso.sharepoint.com"}


def test_no_external_urls_in_source() -> None:
    """Every http(s) URL in source targets loopback, or the M365 exception."""
    offenders: list[tuple[str, str]] = []
    for py in SRC.rglob("*.py"):
        in_m365 = _M365_PKG in py.parents
        for host in _URL_RE.findall(py.read_text(encoding="utf-8")):
            bare = host.split(":")[0]
            if bare in _LOOPBACK or bare in _DOC_PLACEHOLDERS:
                continue
            if in_m365 and bare in _M365_HOSTS:
                continue
            offenders.append((str(py), host))
    assert not offenders, f"Non-local URLs found: {offenders}"


def test_microsoft_endpoints_stay_inside_the_m365_package() -> None:
    """Graph must not leak into the rest of the codebase.

    The integration is meant to be one isolated, switchable-off module. A
    Graph URL appearing in the dashboard, the CLI internals or the task store
    would mean it had stopped being separable.
    """
    offenders: list[tuple[str, str]] = []
    for py in SRC.rglob("*.py"):
        if _M365_PKG in py.parents:
            continue
        for host in _URL_RE.findall(py.read_text(encoding="utf-8")):
            if host.split(":")[0] in _M365_HOSTS:
                offenders.append((str(py), host))
    assert not offenders, f"Graph URLs outside src/hermes_assistant/m365: {offenders}"


def test_the_m365_integration_ships_disabled() -> None:
    """The guard above allows the exception only because it is opt-in."""
    from hermes_assistant.config import Settings

    assert Settings().m365_enabled is False


def test_client_default_host_is_loopback() -> None:
    """The client defaults to a loopback Ollama host."""
    host = OllamaClient().host
    assert any(lb in host for lb in _LOOPBACK)


# --------------------------------------------------------------------------- #
# Unidirectional egress
#
# The rule, stated once: **pulling content in is allowed; project data going
# out is not.** HERMES may ask a question of a remote service and read the
# answer; it may not upload a plan, a risk register or a meeting note.
#
# These tests exist because that is exactly the kind of rule that decays into
# a comment nobody reads. The Chat API was built here and then removed for
# this reason — a chat turn is a push by construction, since carrying context
# outward is its entire purpose. What follows makes the removal a property of
# the code rather than a decision someone has to keep re-making.
# --------------------------------------------------------------------------- #


def test_the_only_remote_call_is_a_retrieval() -> None:
    """One outbound path, and it is a read.

    Asserted against the Graph paths the client can build, not against a list
    of function names: a new method that posts somewhere else would be caught,
    a renamed one would not be a false alarm.
    """
    import re as _re

    client_src = (_M365_PKG / "client.py").read_text(encoding="utf-8")
    paths = set(_re.findall(r'_post\(\s*[fr]?["\']([^"\']+)', client_src))
    paths |= set(_re.findall(r'_url\(\s*[fr]?["\']([^"\']+)', client_src))
    assert paths == {"/copilot/retrieval"}, f"unexpected outbound paths: {paths}"


def test_the_chat_api_is_gone_and_stays_gone() -> None:
    """Its absence is the feature. A helpful re-add would silently reopen the
    one channel that carries project content outward."""
    from hermes_assistant.m365.client import CopilotClient

    for name in ("chat", "start_conversation"):
        assert not hasattr(CopilotClient, name), f"CopilotClient.{name} is back"

    src = (_M365_PKG / "client.py").read_text(encoding="utf-8")
    assert "/copilot/conversations" not in src


def test_no_scope_grants_more_than_reading_files_and_sites() -> None:
    """A scope is a promise to the person consenting.

    Mail, chat messages and meeting transcripts were requested while the Chat
    API existed. They must not be requestable now: no consent screen can grant
    what nothing asks for.
    """
    from hermes_assistant.m365 import auth

    granted = set()
    for source in (auth.RETRIEVAL_SCOPES, auth.CONNECTOR_SCOPES):
        granted |= set(source)
    granted |= set(auth.scopes_for("sharePoint"))
    granted |= set(auth.scopes_for("externalItem"))

    forbidden = {
        "Mail.Read", "Chat.Read", "ChannelMessage.Read.All",
        "OnlineMeetingTranscript.Read.All", "People.Read.All",
    }
    assert not (granted & forbidden), f"outbound-capable scopes: {granted & forbidden}"
    assert not hasattr(auth, "CHAT_SCOPES")


def test_nothing_writes_to_graph() -> None:
    """Read verbs only. A PUT, PATCH or DELETE against Graph would mean HERMES
    had started changing the tenant rather than reading it."""
    import re as _re

    src = (_M365_PKG / "client.py").read_text(encoding="utf-8")
    verbs = set(_re.findall(r"self\._session\.(\w+)\(", src))
    # requests.Session() is a constructor, not a verb — matching it made this
    # test fail on the very code it is meant to approve.
    verbs |= {v for v in _re.findall(r"requests\.([a-z]\w+)\(", src)}
    assert verbs <= {"post", "get"}, f"non-read verbs against Graph: {verbs}"
