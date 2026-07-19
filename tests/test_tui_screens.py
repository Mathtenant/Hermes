"""Tests for tui.screens factory functions.

These tests are skipped when textual is not installed. They validate that
screens can be instantiated without crashing and that factories raise the
expected ImportError when textual is absent.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hermes_assistant.dashboard_html import DashboardData, load_dashboard_data
from hermes_assistant.jobqueue.jobs import JobStore
from hermes_assistant.tasks.model import Task
from hermes_assistant.tasks.store import TaskStore

_TEXTUAL_INSTALLED = importlib.util.find_spec("textual") is not None
_NOW = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)

pytestmark = pytest.mark.skipif(
    not _TEXTUAL_INSTALLED,
    reason="textual not installed (pip install 'hermes-assistant[tui]')",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_data(tmp_path: Path) -> DashboardData:
    ts = TaskStore(":memory:")
    ts.create(Task(id="", title="Alpha task", node_kind="task"))
    js = JobStore(":memory:")
    proj = tmp_path / "my-project"
    proj.mkdir()
    return load_dashboard_data(None, task_store=ts, job_store=js,
                               projects_root=tmp_path, now=_NOW)


# ---------------------------------------------------------------------------
# Screen factory smoke tests (require textual)
# ---------------------------------------------------------------------------

class TestScreenFactories:
    def test_project_list_screen_instantiates(self, sample_data: DashboardData) -> None:
        from hermes_assistant.tui.screens import make_project_list_screen
        screen = make_project_list_screen(sample_data)
        assert screen is not None

    def test_project_detail_screen_instantiates(self, sample_data: DashboardData) -> None:
        from hermes_assistant.tui.screens import make_project_detail_screen
        screen = make_project_detail_screen("my-project", sample_data)
        assert screen is not None

    def test_pendenzen_screen_instantiates(self, sample_data: DashboardData) -> None:
        from hermes_assistant.tui.screens import make_pendenzen_screen
        screen = make_pendenzen_screen(sample_data)
        assert screen is not None

    def test_reviews_screen_instantiates(self, sample_data: DashboardData) -> None:
        from hermes_assistant.tui.screens import make_reviews_screen
        screen = make_reviews_screen(sample_data)
        assert screen is not None

    def test_help_modal_instantiates(self) -> None:
        from hermes_assistant.tui.screens import make_help_modal
        modal = make_help_modal()
        assert modal is not None

    def test_app_make_returns_object(self) -> None:
        from hermes_assistant.tui.app import _make_app
        app = _make_app()
        assert app is not None


# ---------------------------------------------------------------------------
# ImportError path (always runs — no textual skip guard needed here)
# ---------------------------------------------------------------------------

class TestImportErrorWhenNoTextual:
    """Validate the _require_textual guard raises with a helpful message.

    This test runs always. When textual IS installed, we monkeypatch the
    import to simulate absence.
    """

    def test_screens_raise_without_textual(
        self, monkeypatch: pytest.MonkeyPatch, sample_data: DashboardData
    ) -> None:
        import builtins
        real_import = builtins.__import__

        def _block_textual(name: str, *args: object, **kwargs: object) -> object:
            if name == "textual" or name.startswith("textual."):
                raise ModuleNotFoundError(f"No module named '{name}'")
            return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

        import hermes_assistant.tui.screens as screens_mod
        monkeypatch.setattr(builtins, "__import__", _block_textual)
        # Directly call the guard
        with pytest.raises(ImportError, match="textual"):
            screens_mod._require_textual()
