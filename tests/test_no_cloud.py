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
