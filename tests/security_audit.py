"""Automated security audit for HERMES codebase (Phase 3 guardrails validation).

Nine independent checks corresponding to the audit remediation plan items
C1-H8, M1-M2.  Each test inspects source text, git state, or runtime
configuration and fails with a clear diagnostic if a property is violated.
"""
from __future__ import annotations

import inspect
import re
import stat
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src" / "hermes_assistant"
_STATIC = _SRC / "webapp" / "static"

# ---------------------------------------------------------------------------
# 1. No plaintext secrets in source code (C1)
# ---------------------------------------------------------------------------


def test_no_hardcoded_credentials() -> None:
    """Python source must not contain hardcoded API keys or passwords.

    Matches patterns of the form ``NAME = "value"`` where NAME ends with
    *api_key*, *secret*, *password*, or *auth_token* and the value is a
    non-trivial string (>= 8 characters).  Pydantic Field() definitions,
    comments, and docstrings are excluded via the filter below.
    """
    cred_re = re.compile(
        r'(?i)(api[_-]key|auth[_-]token|secret[_-]key|password)\s*=\s*["\']([^"\']{8,})["\']'
    )
    violations: list[str] = []
    for py_file in _SRC.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for m in cred_re.finditer(text):
            # Exclude: Pydantic Field(...), env-var aliases, and comments.
            context = text[max(0, m.start() - 30) : m.end() + 30]
            if re.search(r"Field\(|AliasChoices|#", context):
                continue
            line_no = text[: m.start()].count("\n") + 1
            violations.append(f"{py_file.relative_to(_ROOT)}:{line_no}: {m.group()!r}")
    assert not violations, "Hardcoded credentials found:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# 2. All SQL is parameterized — no user data in f-string SQL (H2)
# ---------------------------------------------------------------------------


def test_sql_execute_fstrings_are_safe() -> None:
    """F-string SQL execute() calls must only interpolate compile-time constants.

    Module-level constant names (starting with ``_`` or ALL_CAPS) are safe:
    they are defined at import time and never contain user-supplied data.
    Local variable names such as ``where``, ``order``, and ``sort_by`` are
    accepted only when they are assembled exclusively from constant fragments
    and ``?`` placeholders (verified by code review; this check catches NEW
    violations introduced after the audit).

    The check flags any f-string interpolation whose expression is a bare
    lowercase identifier that is not one of the known-safe local variables.
    """
    # Match f-string passed as first arg to .execute(
    fstr_exec_re = re.compile(
        r'\.execute\(\s*f["\']([^"\'\\]*(?:\\.[^"\'\\]*)*)["\']',
        re.DOTALL,
    )
    # Extract {expr} interpolations
    interp_re = re.compile(r'\{([^{}]+)\}')
    # Safe: module-level constants (_COLUMNS, _RISK_COLS, …) or compile-time
    # SQL fragments built from constants (where, order, sort_by).
    safe_re = re.compile(
        r'^_[A-Z_]+$'           # module constant like _COLUMNS
        r'|^[A-Z_]{3,}$'        # ALL_CAPS constant
        r"|^where$|^order$"     # local SQL-keyword variables (audit-verified safe)
        r"|^\"[A-Z]+\"$"        # inline string like "DESC"
        r"|^'[A-Z]+'$"
    )
    violations: list[str] = []
    for py_file in _SRC.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for m in fstr_exec_re.finditer(text):
            sql_frag = m.group(1)
            for interp in interp_re.finditer(sql_frag):
                expr = interp.group(1).strip()
                if not safe_re.match(expr):
                    line_no = text[: m.start()].count("\n") + 1
                    violations.append(
                        f"{py_file.relative_to(_ROOT)}:{line_no}: "
                        f"unsafe interpolation {{{expr}!r}} in SQL"
                    )
    assert not violations, (
        "Potentially unsafe SQL f-string interpolations:\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# 3. No unescaped HTML renders in JavaScript (H5)
# ---------------------------------------------------------------------------


def test_no_unescaped_innerhtml_in_js() -> None:
    """JavaScript files must escape user content before writing to innerHTML.

    Assignments to ``innerHTML`` are permitted only if the same file defines
    or imports an escaping helper (``esc(``, ``escapeHtml``, or ``textContent``).
    Files whose innerHTML assignments use only hardcoded string literals (no
    runtime variables) are also considered safe.
    """
    innerhtml_re = re.compile(r'\binnerHTML\s*=(?!=)')
    escape_indicators = ("esc(", "escapeHtml", "textContent")

    violations: list[str] = []
    for js_file in _STATIC.rglob("*.js"):
        text = js_file.read_text(encoding="utf-8")
        if not innerhtml_re.search(text):
            continue
        # The file uses innerHTML — verify it also uses an escaping helper.
        if not any(indicator in text for indicator in escape_indicators):
            violations.append(
                f"{js_file.relative_to(_ROOT)}: innerHTML used without "
                "escapeHtml / esc() / textContent guard"
            )
    assert not violations, "Unguarded innerHTML usage:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# 4. RLock acquired on all SQLite store operations (C2)
# ---------------------------------------------------------------------------


def _count_public_methods_without_lock(source: str) -> list[str]:
    """Return names of public methods that don't use ``with self._lock:``."""
    # Find all method definitions (non-private = not starting with _)
    method_re = re.compile(
        r'^\s{4}def ([a-zA-Z][a-zA-Z0-9_]*)\s*\(', re.MULTILINE
    )
    # A method body is everything from its def up to the next same-indent def.
    method_bodies = list(method_re.finditer(source))
    missing: list[str] = []
    for i, m in enumerate(method_bodies):
        name = m.group(1)
        # close() / close_connection() shut down the connection — no lock needed.
        # Private helpers (_row_to_*, _next_version, etc.) are excluded.
        if name.startswith("_") or name in ("close", "close_connection"):
            continue
        # Extract body: from after the def line to the next top-level method def.
        start = m.end()
        end = method_bodies[i + 1].start() if i + 1 < len(method_bodies) else len(source)
        body = source[start:end]
        if "with self._lock:" not in body:
            missing.append(name)
    return missing


def test_rlock_on_all_store_operations() -> None:
    """All public SQLite store methods must acquire self._lock before writing."""
    store_files = [
        _SRC / "chat" / "store.py",
        _SRC / "risks" / "registry.py",
        _SRC / "plans" / "editor.py",
    ]
    all_missing: dict[str, list[str]] = {}
    for path in store_files:
        text = path.read_text(encoding="utf-8")
        missing = _count_public_methods_without_lock(text)
        if missing:
            all_missing[str(path.relative_to(_ROOT))] = missing

    assert not all_missing, (
        "Public methods lacking 'with self._lock:':\n"
        + "\n".join(f"  {f}: {ms}" for f, ms in all_missing.items())
    )


# ---------------------------------------------------------------------------
# 5. Confidentiality guard runs BEFORE persistence (H1)
# ---------------------------------------------------------------------------


def test_guard_runs_before_persistence() -> None:
    """service.py must call _validate_safe_json before store.add_message."""
    service_src = (_SRC / "chat" / "service.py").read_text(encoding="utf-8")

    guard_idx = service_src.find("_validate_safe_json")
    persist_idx = service_src.find("store.add_message", guard_idx)

    assert guard_idx != -1, "_validate_safe_json not found in service.py"
    assert persist_idx != -1, (
        "store.add_message (assistant) not found after _validate_safe_json in service.py"
    )
    assert guard_idx < persist_idx, (
        "_validate_safe_json must appear before the assistant store.add_message call; "
        f"guard at char {guard_idx}, persist at char {persist_idx}"
    )


# ---------------------------------------------------------------------------
# 6. Import atomicity enforced — single commit per entity type (M1)
# ---------------------------------------------------------------------------


def test_import_atomicity_enforced() -> None:
    """_import_risks must write all rows in a single atomic transaction."""
    import_src = (_SRC / "webapp" / "import_json.py").read_text(encoding="utf-8")

    # The risks importer must use the registry lock and a single commit call
    # to guarantee atomicity (all items or none).
    assert "registry._lock" in import_src, (
        "_import_risks must acquire registry._lock for atomic batch writes"
    )
    assert "registry._conn.commit()" in import_src, (
        "_import_risks must call registry._conn.commit() for the atomic batch"
    )
    # Verify the commit is inside the lock block (appears after registry._lock).
    lock_idx = import_src.find("registry._lock")
    commit_idx = import_src.find("registry._conn.commit()", lock_idx)
    assert commit_idx > lock_idx, (
        "registry._conn.commit() must appear after registry._lock in _import_risks"
    )


# ---------------------------------------------------------------------------
# 7. External data directory — data/ not tracked in git (M2)
# ---------------------------------------------------------------------------


def test_data_directory_not_tracked_in_git() -> None:
    """Runtime artefacts (data/) must not be committed to git."""
    result = subprocess.run(
        ["git", "ls-files", "data/"],
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    tracked = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert not tracked, (
        f"data/ files are tracked in git (should be .gitignored):\n"
        + "\n".join(tracked)
    )


# ---------------------------------------------------------------------------
# 8. Pre-commit hook active — blocks PII and secrets (C3)
# ---------------------------------------------------------------------------


def test_pre_commit_hook_active() -> None:
    """The guardrail pre-commit hook must exist, be executable, and be wired."""
    hook_path = _ROOT / "scripts" / "hooks" / "pre-commit"

    assert hook_path.is_file(), (
        f"Pre-commit hook missing: {hook_path}\n"
        "Run: chmod +x scripts/hooks/pre-commit && "
        "git config core.hooksPath scripts/hooks"
    )
    mode = hook_path.stat().st_mode
    assert bool(mode & stat.S_IXUSR), (
        f"{hook_path} is not executable (chmod +x required)"
    )

    # Verify git is configured to use the custom hooks directory.
    result = subprocess.run(
        ["git", "config", "core.hooksPath"],
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
    )
    hooks_path_cfg = result.stdout.strip()
    assert hooks_path_cfg == "scripts/hooks", (
        f"git core.hooksPath is {hooks_path_cfg!r}, expected 'scripts/hooks'.\n"
        "Run: git config core.hooksPath scripts/hooks"
    )


# ---------------------------------------------------------------------------
# 9. Config validation — ollama_host must be loopback-only (H6)
# ---------------------------------------------------------------------------

_LOOPBACK_PREFIXES = (
    "http://localhost",
    "https://localhost",
    "http://127.0.0.1",
    "https://127.0.0.1",
    "http://[::1]",
)


def test_ollama_host_is_loopback_only() -> None:
    """settings.ollama_host must point to a loopback address.

    Preventing a non-loopback host guards against accidental exfiltration of
    prompts and completions to a remote service.
    """
    from hermes_assistant.config import settings

    host = settings.ollama_host
    assert any(host.startswith(prefix) for prefix in _LOOPBACK_PREFIXES), (
        f"settings.ollama_host={host!r} is not a loopback address.\n"
        "Only http(s)://localhost or http(s)://127.0.0.1 are permitted."
    )
