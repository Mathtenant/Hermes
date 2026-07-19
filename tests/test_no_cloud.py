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


def test_no_external_urls_in_source() -> None:
    """Every http(s) URL in source targets a loopback host."""
    offenders: list[tuple[str, str]] = []
    for py in SRC.rglob("*.py"):
        for host in _URL_RE.findall(py.read_text(encoding="utf-8")):
            bare = host.split(":")[0]
            if bare not in _LOOPBACK:
                offenders.append((str(py), host))
    assert not offenders, f"Non-local URLs found: {offenders}"


def test_client_default_host_is_loopback() -> None:
    """The client defaults to a loopback Ollama host."""
    host = OllamaClient().host
    assert any(lb in host for lb in _LOOPBACK)
