# HERMES Security Model

HERMES is designed to process sensitive project-management data on a local
machine.  Five independent guardrail layers prevent confidential information
from leaking into git history, log files, or API responses.

---

## Layer 1 — External Data Directory

**What it does:** All runtime SQLite databases (tasks, job queue) are stored
outside the repository tree in a platform-specific directory.

| Platform | Default path |
|----------|-------------|
| macOS / Linux | `~/.hermes/data/` |
| Windows | `%LOCALAPPDATA%\hermes-data\` |

**Override:** Set the `HERMES_DATA_DIR` environment variable to any writable
directory.

**Why it matters:** Keeping databases outside the repo means `git add .` can
never accidentally stage a database file, even if `.gitignore` is incomplete.

---

## Layer 2 — HTTP Security Headers

**What it does:** Every response from the FastAPI server carries hardened
HTTP headers set by `_SecurityHeadersMiddleware` in `webapp/server.py`:

- `Content-Security-Policy` — restricts script and style sources
- `X-Content-Type-Options: nosniff` — prevents MIME-type sniffing
- `X-Frame-Options: DENY` — blocks clickjacking
- `Referrer-Policy: no-referrer` — suppresses referrer leakage

**Why it matters:** The dashboard is served locally but may be opened in a
browser alongside untrusted tabs.

---

## Layer 3 — Pre-Commit Hook

**What it does:** The `scripts/hooks/pre-commit` shell script inspects every
staged file before `git commit` completes and aborts if any of these are
found:

| Pattern | Reason |
|---------|--------|
| `*.db`, `*.db-wal`, `*.db-shm` | SQLite runtime files |
| `.env*` | Credentials and secrets |
| `*.log` | Raw LLM traces that may contain verbatim input |
| `__pycache__/`, `node_modules/`, etc. | Build artefacts |
| Terms in `.hermes/pii_terms.txt` | Organisation-specific PII |

**Activation (one-time, per working copy):**
```bash
git config core.hooksPath scripts/hooks
```

**Why it matters:** Even with a correct `.gitignore`, a developer can
accidentally `git add` a specific file by name.  The hook is the last line
of defence before history is written.

---

## Layer 4 — API Response Validation

**What it does:** `_validate_safe_json()` in `webapp/server.py` scans every
JSON payload before it leaves the server and rejects responses that contain:

- Exact forbidden field names: `raw_notes`, `evidence_quote`, `rationale`,
  `fix_suggestion`, `open_assumptions`, `assumptions`
- Field names matching `internal_*` or `confidential_*` patterns
- Absolute filesystem paths (e.g. `/Users/…`, `/home/…`, `C:\…`)
- Email addresses

**Endpoints covered:**
- `GET /api/health` — guarded by `@confidentiality_guard` decorator
- `GET /api/dashboard` — guarded inline; raises HTTP 500 on violation
- `GET /api/refresh` — delegates to `/api/dashboard`

**Why it matters:** Pydantic view models use `extra="forbid"` to block
confidential fields at construction time, but the response validator is
a second independent check that catches accidental bypasses.

---

## Layer 5 — PII Terms Dictionary

**What it does:** `.hermes/pii_terms.txt` is a plain-text list of terms
(one per line) that the pre-commit hook searches for in every staged diff.
Commits containing any listed term are rejected.

**Extending the list:**
1. Open `.hermes/pii_terms.txt`.
2. Add one term per line; use `#` for comments.
3. Commit the updated dictionary (the terms themselves are not PII).

**Why it matters:** Customer names, project code names, and internal system
identifiers are not known in advance.  The dictionary lets operators
customise the guardrail without modifying source code.

---

## Summary

| Layer | Where | Blocks |
|-------|-------|--------|
| 1 — External data dir | `config.py` | DB files outside repo |
| 2 — Security headers | `webapp/server.py` | Browser-based attacks |
| 3 — Pre-commit hook | `scripts/hooks/pre-commit` | Accidental commits |
| 4 — Response validator | `webapp/server.py` | Confidential field leakage |
| 5 — PII dictionary | `.hermes/pii_terms.txt` | Organisation-specific terms |
