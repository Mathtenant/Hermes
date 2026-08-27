"""Tests for data-directory isolation (Layer 1b of the guardrail stack).

Verifies that runtime SQLite databases default to a location *outside* the
git repository (``~/.hermes/data``), that ``HERMES_DATA_DIR`` overrides it,
and that no ``data/**`` runtime artefacts are tracked by git.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _restore_config_module():
    """Undo the module reloads these tests perform.

    ``_fresh_settings`` calls ``importlib.reload`` on the config module, which
    rebinds ``config.settings`` to a brand-new object. Every module that did
    ``from hermes_assistant.config import settings`` at import time keeps the
    *old* object, so from then on the two names disagree — and a later test
    patching ``hermes_assistant.config.settings`` silently fails to affect the
    code under test. Putting the original object back on the way out realigns
    the two names, so the divergence stays inside this file. (Reloading again
    would not do it — that just mints a third object.)
    """
    import hermes_assistant.config as config_module

    original = config_module.settings
    try:
        yield
    finally:
        config_module.settings = original


def _fresh_settings(monkeypatch, **env: str):
    """Import a fresh hermes_assistant.config.Settings honouring the given env."""
    import importlib

    import hermes_assistant.config as config_module

    for key, value in env.items():
        monkeypatch.setenv(key, value)
    importlib.reload(config_module)
    return config_module


def test_default_data_dir_outside_repo(monkeypatch) -> None:
    monkeypatch.delenv("HERMES_DATA_DIR", raising=False)
    config_module = _fresh_settings(monkeypatch)
    data_dir = Path(config_module.settings.data_dir)
    assert str(_REPO_ROOT) not in str(data_dir)
    assert data_dir == Path.home() / ".hermes" / "data"


def test_hermes_data_dir_env_var_overrides_default(monkeypatch, tmp_path: Path) -> None:
    custom = str(tmp_path / "custom-hermes-data")
    config_module = _fresh_settings(monkeypatch, HERMES_DATA_DIR=custom)
    assert config_module.settings.data_dir == custom


def test_tasks_db_path_derived_from_default_data_dir(monkeypatch) -> None:
    monkeypatch.delenv("HERMES_DATA_DIR", raising=False)
    config_module = _fresh_settings(monkeypatch)
    tasks_db = Path(config_module.settings.tasks_db_path)
    assert str(_REPO_ROOT) not in str(tasks_db)
    assert ".hermes" in str(tasks_db)


def test_no_data_artifacts_tracked_by_git() -> None:
    """No `data/**` runtime files (db/log/jsonl) should ever be committed."""
    result = subprocess.run(
        ["git", "ls-files", "data/"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked = [line for line in result.stdout.splitlines() if line.strip()]
    forbidden_suffixes = (".db", ".db-wal", ".db-shm", ".log", ".jsonl")
    leaked = [f for f in tracked if f.endswith(forbidden_suffixes)]
    assert leaked == [], f"Runtime data artefacts tracked by git: {leaked}"
