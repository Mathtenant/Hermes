"""Tests for the HERMES-Guardrail pre-commit hook (scripts/hooks/pre-commit).

The hook is a standalone bash script that inspects ``git diff --cached``
and refuses to let confidential/runtime artefacts be committed. These
tests exercise the real script (not a reimplementation) against disposable
temp git repositories so behaviour changes are caught immediately.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HOOK_PATH = _REPO_ROOT / "scripts" / "hooks" / "pre-commit"
_PII_TERMS_PATH = _REPO_ROOT / ".hermes" / "pii_terms.txt"

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or not _HOOK_PATH.is_file(),
    reason="git or scripts/hooks/pre-commit not available",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_repo(tmp_path: Path, *, with_pii_terms: bool = True) -> Path:
    """Create a throwaway git repo, optionally seeded with the PII dictionary."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    if with_pii_terms and _PII_TERMS_PATH.is_file():
        hermes_dir = repo / ".hermes"
        hermes_dir.mkdir()
        (hermes_dir / "pii_terms.txt").write_text(
            _PII_TERMS_PATH.read_text(encoding="utf-8"), encoding="utf-8"
        )
        subprocess.run(["git", "add", ".hermes/pii_terms.txt"], cwd=repo, check=True)
        # Commit the dictionary itself in its own commit so later `git diff
        # --cached` calls (for the file actually under test) don't see the
        # dictionary's own entries (e.g. "acme corp") as part of the staged
        # diff and false-positive against themselves.
        subprocess.run(
            ["git", "commit", "-q", "-m", "seed pii terms"], cwd=repo, check=True
        )
    else:
        # Still give the repo an initial commit so HEAD exists (some git
        # commands, e.g. `git restore --staged`, require it).
        (repo / ".gitkeep").write_text("", encoding="utf-8")
        subprocess.run(["git", "add", ".gitkeep"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


def _stage(repo: Path, rel_path: str, content: str = "x") -> None:
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-f", rel_path], cwd=repo, check=True)


def _run_hook(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(_HOOK_PATH)], cwd=repo, capture_output=True, text=True
    )


# ---------------------------------------------------------------------------
# Forbidden extensions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("filename", ["state.db", "state.db-wal", "state.db-shm", "run.log"])
def test_hook_blocks_forbidden_extension(tmp_path: Path, filename: str) -> None:
    repo = _make_repo(tmp_path)
    _stage(repo, filename)
    result = _run_hook(repo)
    assert result.returncode != 0
    assert "blocked" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Credential files
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("filename", [".env", ".env.local", ".env.production"])
def test_hook_blocks_env_files(tmp_path: Path, filename: str) -> None:
    repo = _make_repo(tmp_path)
    _stage(repo, filename)
    result = _run_hook(repo)
    assert result.returncode != 0
    assert "credential" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Build/runtime artefact directories
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rel_path",
    [
        "src/pkg/__pycache__/mod.cpython-311.pyc",
        "web/node_modules/left-pad/index.js",
        "dist/hermes_assistant.egg-info/PKG-INFO",
    ],
)
def test_hook_blocks_build_artifact_dirs(tmp_path: Path, rel_path: str) -> None:
    repo = _make_repo(tmp_path)
    _stage(repo, rel_path)
    result = _run_hook(repo)
    assert result.returncode != 0
    assert "runtime/build folder blocked" in result.stdout.lower() or "blocked" in result.stdout.lower()


# ---------------------------------------------------------------------------
# PII terms dictionary scan
# ---------------------------------------------------------------------------


def test_hook_scans_pii_terms_case_insensitive(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    # "confidential" is one of the seeded terms; check case-insensitive match.
    _stage(repo, "notes.md", "This project is CONFIDENTIAL and must not leak.")
    result = _run_hook(repo)
    assert result.returncode != 0
    assert "pii term detected" in result.stdout.lower()


def test_hook_missing_pii_file_does_not_crash(tmp_path: Path) -> None:
    """If .hermes/pii_terms.txt is absent, the hook must not error out."""
    repo = _make_repo(tmp_path, with_pii_terms=False)
    _stage(repo, "notes.md", "Nothing sensitive here.")
    result = _run_hook(repo)
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Safe files are allowed through
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename,content",
    [
        ("module.py", "def hello():\n    return 'world'\n"),
        ("README.md", "# Docs\n\nNothing sensitive here.\n"),
        ("config.json", '{"key": "value"}\n'),
    ],
)
def test_hook_allows_safe_files(tmp_path: Path, filename: str, content: str) -> None:
    repo = _make_repo(tmp_path)
    _stage(repo, filename, content)
    result = _run_hook(repo)
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# End-to-end git integration (core.hooksPath)
# ---------------------------------------------------------------------------


def test_hook_integration_with_git_hookspath(tmp_path: Path) -> None:
    """Configuring core.hooksPath makes `git commit` actually invoke the hook."""
    repo = _make_repo(tmp_path)
    hooks_dir = repo / "scripts" / "hooks"
    hooks_dir.mkdir(parents=True)
    hook_copy = hooks_dir / "pre-commit"
    hook_copy.write_text(_HOOK_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    hook_copy.chmod(0o755)
    subprocess.run(["git", "add", "scripts/hooks/pre-commit"], cwd=repo, check=True)
    # Commit the hook file itself *before* activating core.hooksPath, so its
    # own addition isn't subject to the hook that doesn't exist yet.
    subprocess.run(
        ["git", "commit", "-q", "-m", "install hook"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "core.hooksPath", "scripts/hooks"], cwd=repo, check=True)

    # A confidential runtime file must be rejected by `git commit` itself.
    _stage(repo, "runtime.db")
    commit = subprocess.run(
        ["git", "commit", "-m", "add db"], cwd=repo, capture_output=True, text=True
    )
    assert commit.returncode != 0
    assert "blocked" in (commit.stdout + commit.stderr).lower()

    # Unstage the bad file, commit a clean one instead — must succeed.
    subprocess.run(["git", "restore", "--staged", "runtime.db"], cwd=repo, check=True)
    _stage(repo, "clean.py", "print('ok')\n")
    commit2 = subprocess.run(
        ["git", "commit", "-m", "add clean file"], cwd=repo, capture_output=True, text=True
    )
    assert commit2.returncode == 0


def test_hook_clean_commit_exit_zero(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _stage(repo, "src/thing.py", "x = 1\n")
    result = _run_hook(repo)
    assert result.returncode == 0
    assert result.stdout.strip() == "" or "blocked" not in result.stdout.lower()
