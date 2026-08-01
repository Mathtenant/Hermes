# HERMES Assistant — Guardrails Activation & Verification

Version: Phase 5  
Date: 2026-08-01

This document describes the 5-layer defense-in-depth guardrail system for HERMES Assistant, how to verify each layer is active, how to customize them, and how to respond to a suspected data leak.

---

## Overview: 5-Layer Defense

```
Layer 1: Pre-commit hook        →  blocks .db, .env, PII before commit
Layer 2: PII term dictionary    →  customizable term scan on staged diffs
Layer 3: API confidentiality    →  blocks forbidden fields in API responses
Layer 4: External data dir      →  runtime artifacts never touch the repo
Layer 5: RLock serialization    →  prevents concurrent data corruption
```

---

## Layer 1 — Pre-commit Hook

**File:** `scripts/hooks/pre-commit`  
**What it blocks:**
- File extensions: `.db`, `.db-wal`, `.db-shm`, `.log`
- Credential files: `.env`, `.env.*`
- Runtime/build folders: `__pycache__/`, `node_modules/`, `.pytest_cache/`, `build/`, `dist/`, `.egg-info/`
- PII terms from `.hermes/pii_terms.txt` in staged diffs (non-test files)

### Activate

```bash
git config core.hooksPath scripts/hooks
```

This is a one-time command per clone. The bootstrap script runs it automatically.

### Verify It Is Active

```bash
git config core.hooksPath
# Should print: scripts/hooks
```

```bash
# Test: attempt to stage a .db file
touch test_block.db
git add test_block.db
git commit -m "test"
# Expected output:
# HERMES-Guardrail: runtime/confidential file blocked: *.db
# Commit should be aborted (exit 1)
git restore --staged test_block.db
rm test_block.db
```

### What Happens on a Violation

The hook prints a message identifying the blocked pattern, then exits with code 1. Git aborts the commit. No files are committed. The developer must remove the offending file from staging with `git restore --staged <file>` before retrying.

---

## Layer 2 — PII Detection (Term Dictionary)

**File:** `.hermes/pii_terms.txt`  
**What it does:** Scans all staged diff additions in non-test files for any of the listed terms (case-insensitive). If a match is found, the commit is blocked.

### Current Terms

```
secret
password
api_key
access_token
private_key
```

(Plus any organization-specific terms added below the comment block.)

### Customize PII Terms

Edit `.hermes/pii_terms.txt` and add one term per line:

```bash
# Example: add company-internal project codenames
echo "project-atlas" >> .hermes/pii_terms.txt
echo "customer_id" >> .hermes/pii_terms.txt
```

Lines starting with `#` and blank lines are ignored.

### Verify It Is Active

```bash
cat .hermes/pii_terms.txt
# Should list at least: secret, password, api_key, access_token, private_key

# Test: attempt to commit a file with a PII term
echo "password=hunter2" > /tmp/pii_test.txt
cp /tmp/pii_test.txt pii_test.txt
git add pii_test.txt
git commit -m "test"
# Expected: HERMES-Guardrail: PII term detected in staged diff: "password"
git restore --staged pii_test.txt
rm pii_test.txt
```

### Why Test Files Are Exempt

Test files (paths starting with `tests/`) are excluded from PII scanning. Security tests legitimately reference PII patterns (e.g., `test_pre_commit_hook.py` asserts that "password" is blocked). The hook only scans non-test source files.

---

## Layer 3 — API Confidentiality Guards

**File:** `src/hermes_assistant/webapp/server.py` (`_validate_safe_json`)  
**What it does:** Before any API response is serialized to JSON, `_validate_safe_json` recursively walks the response object and raises `HTTPException(403)` if it encounters any forbidden field name or value pattern.

**Forbidden patterns include:**
- Field names: `password`, `secret`, `token`, `api_key`, `private_key`, `credentials`
- Value patterns matching common credential formats (e.g., base64 secrets, bearer tokens in response bodies)

### Verify It Is Active

```bash
# Run the confidentiality guard tests
python3.11 -m pytest tests/test_confidentiality_guards.py -v
# Expected: all pass
```

### How It Fits Into the Request Cycle

```
HTTP Request → FastAPI route handler → business logic
    → _validate_safe_json(response_data) → raise 403 if unsafe
    → JSONResponse to client
```

Any route that inadvertently includes a credential field in its response will fail at this layer before the data reaches the client.

---

## Layer 4 — External Data Directory

**Configuration:** `HERMES_DATA_DIR` env var (default: `./data`)  
**What it does:** All runtime artifacts (SQLite databases, LLM traces, job queue files) are written to a directory that is:
1. Listed in `.gitignore` (pattern: `data/**/*.db`, `data/**/*.jsonl`, `*.log`)
2. Never committed (pre-commit hook blocks `.db` and `.log` extensions)
3. Separate from the source tree in production deployments (set `HERMES_DATA_DIR=~/.hermes/data`)

### Verify It Is Active

```bash
# Confirm data dir is gitignored
git check-ignore -v data/risks.db
# Should output: .gitignore:30:data/**/*.db    data/risks.db

# Confirm no db files are tracked
git ls-files data/
# Should return empty output
```

### Setting an External Data Directory

```bash
export HERMES_DATA_DIR=/var/lib/hermes/data
mkdir -p $HERMES_DATA_DIR/queue $HERMES_DATA_DIR/traces
# Restart the server — all new files go to the external path
```

---

## Layer 5 — RLock Serialization

**Modules:** `ChatStore`, `RiskRegistry`, `TaskStore`, `JobStore`  
**What it does:** Each store class holds a `threading.RLock` instance. All public methods acquire the lock before reading or writing. This prevents race conditions when multiple HTTP request handlers or background workers access the same store simultaneously.

RLock (reentrant lock) is used rather than Lock to allow a single thread to acquire the lock multiple times (e.g., when a store method calls another store method internally).

### Why This Matters

Without serialization, concurrent writes to SQLite can cause:
- `OperationalError: database is locked`
- Partial writes (corrupt records)
- Lost updates (last-write-wins with stale data)

With RLock, only one thread can modify a store at a time. Reads are also serialized to prevent dirty reads against in-memory caches.

### Verify It Is Active

```bash
# Run concurrent store tests
python3.11 -m pytest tests/test_concurrent_stores.py -v
# Expected: all pass — no deadlocks, no AssertionErrors
```

### Inspecting Lock Behavior

To verify a store uses RLock:

```python
from hermes_assistant.chat.store import ChatStore
import inspect
src = inspect.getsource(ChatStore.__init__)
print("_lock" in src and "RLock" in src)  # Should print: True
```

---

## Adding New Guardrails

### Add a New PII Term

```bash
echo "new_sensitive_term" >> .hermes/pii_terms.txt
git add .hermes/pii_terms.txt
git commit -m "security: add new_sensitive_term to PII dictionary"
```

### Add a New Forbidden API Field

In `src/hermes_assistant/webapp/server.py`, extend the `FORBIDDEN_FIELDS` set or pattern list inside `_validate_safe_json`.

### Add a New File Extension to Pre-commit Hook

In `scripts/hooks/pre-commit`, add the extension to `FORBIDDEN_EXTS`:

```bash
FORBIDDEN_EXTS=(".db" ".db-wal" ".db-shm" ".log" ".pem")
```

### Add RLock to a New Store

```python
import threading

class MyNewStore:
    def __init__(self, db_path: str) -> None:
        self._lock = threading.RLock()
        self._db_path = db_path

    def write(self, data: dict) -> None:
        with self._lock:
            # perform write
            ...

    def read(self, key: str) -> dict:
        with self._lock:
            # perform read
            ...
```

---

## Security Incident Response

If a data leak is suspected (e.g., a credential appeared in a commit or API response):

### Step 1 — Identify the Leak

```bash
# Search git history for the term
git log --all -S "suspected_term" --oneline

# Search current tree
grep -r "suspected_term" src/ tests/ --include="*.py"
```

### Step 2 — Remove From Git History (if committed)

```bash
# Revoke the credential FIRST (before attempting cleanup)
# Then use git filter-repo or BFG Repo Cleaner:
pip install git-filter-repo
git filter-repo --replace-text <(echo "suspected_term==>REDACTED")
```

### Step 3 — Rotate Credentials

Regardless of whether the cleanup succeeded, treat the credential as compromised. Rotate API keys, passwords, or tokens immediately.

### Step 4 — Harden the Guardrails

Add the leaked term to `.hermes/pii_terms.txt` and to the API confidentiality guard so future occurrences are blocked at the source.

### Step 5 — Audit API Responses

```bash
# Review LLM trace logs for any sensitive content
grep -i "suspected_term" data/traces/llm_trace.jsonl
```

### Step 6 — Notify Stakeholders

If the leak affected project data (not just local dev credentials), notify the project security contact and document the incident.

---

## Guardrail Test Coverage

| Test File | What It Covers |
|-----------|---------------|
| `tests/test_pre_commit_hook.py` | Layer 1: hook blocks .db, .env, PII terms |
| `tests/test_confidentiality_guards.py` | Layer 3: API response filtering |
| `tests/security_audit.py` | Layers 1, 2, 4: file tracking, gitignore, hook presence |
| `tests/test_concurrent_stores.py` | Layer 5: RLock under concurrent load |
| `tests/test_config_isolation.py` | Layers 1, 4: no runtime artifacts in git |
