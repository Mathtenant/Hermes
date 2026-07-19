"""Phase P5a tests — panel roster, weighted_vote, resolve_panel.

All tests are deterministic and offline (no live model required).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from hermes_assistant.agents.critic import CheckSample
from hermes_assistant.agents.panel import PanelVote, resolve_panel, weighted_vote
from hermes_assistant.config import settings
from hermes_assistant.hermes.model import Severity
from hermes_assistant.llm.client import OllamaClient
from hermes_assistant.llm.roster import PANEL, ModelConfig, get_panel_configs

from .conftest import make_response

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _cs(result: str) -> CheckSample:
    """Build a minimal CheckSample for the given result."""
    return CheckSample(
        location="sec 1",
        evidence_quote="some text",
        rationale="because",
        result=result,  # type: ignore[arg-type]
        severity=Severity.minor,
        fix_suggestion="fix it",
    )


def _vote(model: str, result: str, weight: float = 1.0, *, ev: bool = True) -> PanelVote:
    return PanelVote(
        model=model,
        result=result,  # type: ignore[arg-type]
        weight=weight,
        evidence_verified=ev,
        sample=_cs(result),
    )


# --------------------------------------------------------------------------- #
# weighted_vote
# --------------------------------------------------------------------------- #

def test_weighted_vote_majority() -> None:
    """3 equal-weight votes {pass, pass, fail} -> pass with confidence 2/3."""
    votes = [
        _vote("qwen3:8b", "pass"),
        _vote("gemma3:4b", "pass"),
        _vote("llama3.1:8b", "fail"),
    ]
    result, conf = weighted_vote(votes)
    assert result == "pass"
    assert conf == pytest.approx(2.0 / 3.0, abs=1e-6)


def test_weighted_vote_weighted() -> None:
    """Weighted votes: qwen(pass,w=2), gemma(pass,w=1), llama(fail,w=1).

    pass_sum = 2+1 = 3, fail_sum = 1, total = 4 -> pass at confidence 3/4.
    Higher-weight model amplifies the majority.
    """
    votes = [
        _vote("qwen3:8b", "pass", 2.0),
        _vote("gemma3:4b", "pass", 1.0),
        _vote("llama3.1:8b", "fail", 1.0),
    ]
    result, conf = weighted_vote(votes)
    assert result == "pass"
    assert conf == pytest.approx(3.0 / 4.0, abs=1e-6)


def test_weighted_vote_tie_pessimistic() -> None:
    """Equal-weight tie between fail and pass resolves to fail (pessimistic)."""
    votes = [
        _vote("qwen3:8b", "pass"),
        _vote("gemma3:4b", "fail"),
    ]
    result, conf = weighted_vote(votes)
    assert result == "fail"
    assert conf == pytest.approx(0.5, abs=1e-6)


def test_weighted_vote_empty() -> None:
    """Empty votes raises ValueError."""
    with pytest.raises(ValueError, match="at least one vote"):
        weighted_vote([])


def test_weighted_vote_zero_weight_guarded() -> None:
    """A zero-weight vote is excluded from the denominator.

    votes: qwen(pass,w=1), gemma(pass,w=1), llama(fail,w=0)
    Denominator = 2 (llama excluded), pass_sum = 2 -> confidence = 1.0.
    """
    votes = [
        _vote("qwen3:8b", "pass", 1.0),
        _vote("gemma3:4b", "pass", 1.0),
        _vote("llama3.1:8b", "fail", 0.0),  # zero weight, excluded from denom
    ]
    result, conf = weighted_vote(votes)
    assert result == "pass"
    assert conf == pytest.approx(1.0, abs=1e-6)


# --------------------------------------------------------------------------- #
# resolve_panel
# --------------------------------------------------------------------------- #

def test_resolve_panel_default() -> None:
    """Default resolution returns the PANEL roster: qwen3:8b, gemma3:4b, llama3.1:8b."""
    configs = resolve_panel()
    assert len(configs) == 3
    assert configs[0].id == "qwen3:8b"
    assert configs[1].id == "gemma3:4b"
    assert configs[2].id == "llama3.1:8b"


def test_resolve_panel_override_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    """settings.panel_models CSV overrides the default roster."""
    monkeypatch.setattr(settings, "panel_models", "qwen3:4b,llama3.1:8b")
    configs = resolve_panel()
    assert len(configs) == 2
    assert configs[0].id == "qwen3:4b"
    assert configs[1].id == "llama3.1:8b"
    monkeypatch.setattr(settings, "panel_models", "")


# --------------------------------------------------------------------------- #
# critic.py — public criterion_messages export
# --------------------------------------------------------------------------- #

def test_criterion_messages_public() -> None:
    """criterion_messages is importable as a public symbol from critic."""
    from hermes_assistant.agents.critic import criterion_messages  # noqa: F401
    assert callable(criterion_messages)


# --------------------------------------------------------------------------- #
# roster — PANEL configs
# --------------------------------------------------------------------------- #

def test_roster_panel_configs() -> None:
    """PANEL is a list of exactly 3 ModelConfigs with qwen3:8b first."""
    configs = get_panel_configs()
    assert isinstance(PANEL, list)
    assert len(configs) == 3
    assert all(isinstance(c, ModelConfig) for c in configs)
    assert configs[0].id == "qwen3:8b"
    assert configs[1].id == "gemma3:4b"
    assert configs[2].id == "llama3.1:8b"


# --------------------------------------------------------------------------- #
# client — keep_alive passthrough
# --------------------------------------------------------------------------- #

def test_client_keep_alive_passthrough(
    mock_post: MagicMock,
    client: OllamaClient,
) -> None:
    """keep_alive is forwarded as a top-level field in the Ollama request payload."""
    # Build a valid CheckSample JSON response
    mock_post.return_value = make_response(
        {
            "message": {
                "content": (
                    '{"location": "sec 1", "evidence_quote": "some text", '
                    '"rationale": "r", "result": "pass", '
                    '"severity": "minor", "fix_suggestion": "ok"}'
                )
            },
            "prompt_eval_count": 10,
            "eval_count": 5,
        }
    )

    client.structured(
        "qwen3:8b",
        [{"role": "user", "content": "judge this"}],
        CheckSample,
        keep_alive=0,
    )

    payload = mock_post.call_args.kwargs["json"]
    assert "keep_alive" in payload
    assert payload["keep_alive"] == 0
