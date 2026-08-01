"""Settings & roster configuration tests (Pydantic v2)."""

import pytest

from hermes_assistant.config import Settings, settings
from hermes_assistant.llm.roster import (
    ROSTER,
    ModelConfig,
    ModelMode,
    ModelRole,
    get_model,
    get_model_config,
)


def test_settings_defaults() -> None:
    """Defaults point at local loopback and a JSONL trace path."""
    assert settings.ollama_host == "http://localhost:11434"
    assert settings.traces_path.endswith(".jsonl")
    assert settings.ollama_num_thread == 10


def test_settings_uses_pydantic_v2_config() -> None:
    """Migrated off the v1 inner 'class Config' onto model_config."""
    assert hasattr(Settings, "model_config")
    assert Settings.model_config.get("env_file") == ".env"
    # The v1 inner class must be gone.
    assert not isinstance(getattr(Settings, "Config", None), type)


def test_settings_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment variables override defaults (case-insensitive)."""
    monkeypatch.setenv("OLLAMA_NUM_THREAD", "4")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    s = Settings()
    assert s.ollama_num_thread == 4
    assert s.log_level == "DEBUG"


def test_settings_chat_confidence_threshold_default() -> None:
    """M7: chat_confidence_threshold defaults to 0.7."""
    s = Settings()
    assert s.chat_confidence_threshold == 0.7


def test_settings_chat_confidence_threshold_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """M7: chat_confidence_threshold is tunable via environment variable."""
    monkeypatch.setenv("CHAT_CONFIDENCE_THRESHOLD", "0.5")
    s = Settings()
    assert s.chat_confidence_threshold == 0.5


def test_roster_entries_are_modelconfig() -> None:
    """Every roster entry is a typed ModelConfig (not a plain dict)."""
    assert all(isinstance(cfg, ModelConfig) for cfg in ROSTER.values())


def test_roster_values() -> None:
    """Spot-check roster IDs, modes, and the critic fallback."""
    assert get_model(ModelRole.ROUTER) == "qwen3:4b"
    critic = get_model_config(ModelRole.CRITIC)
    assert critic.mode is ModelMode.THINKING
    assert critic.fallback == "gpt-oss:20b"
    assert get_model_config(ModelRole.EMBED).tok_s_estimate is None
