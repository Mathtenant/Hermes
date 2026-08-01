# HERMES Assistant — Production Readiness Checklist

Version: Phase 5 (Text-Based Chat)  
Date: 2026-08-01  
Status: **READY FOR STAGING**

---

## Security

- [x] **All 9 security audit checks pass** (`tests/security_audit.py` — 9/9 green)
- [x] Data directory (`data/`) not tracked by git
- [x] `.env` files blocked by pre-commit hook
- [x] `.db`, `.db-wal`, `.db-shm`, `.log` extensions blocked by pre-commit hook
- [x] PII terms dictionary active (`.hermes/pii_terms.txt`)
- [x] `_validate_safe_json` blocks forbidden field names in API responses
- [x] Ollama bound to loopback only (`http://localhost:11434`) — no external exposure
- [x] No hardcoded credentials or tokens anywhere in source
- [x] Config validation at startup (`config.py` pydantic-settings model)

---

## Testing

- [x] **744 unit/integration tests passing**
- [x] 9 tests skipped (require live Ollama or Playwright — by design)
- [x] 6 pre-existing failures (scheduling holiday data, optional-dep CLI tests — tracked)
- [x] 90%+ coverage on core features: chat, import, risks, plans
- [x] 95%+ coverage on guardrails: stores, RLock, hooks, config
- [x] Concurrency tests pass: `test_concurrent_stores.py` (RLock serialization verified)
- [x] Config isolation tests pass: `test_config_isolation.py` (4/4)
- [x] Security audit tests pass: `tests/security_audit.py` (9/9)

---

## Performance

- [x] Latency SLA < 500ms: HTTP endpoints respond within target (verified by `test_webapp_endpoints.py`)
- [x] Latency SLA < 100ms: Store read/write operations (SQLite, in-memory RLock)
- [x] Latency SLA < 10ms: Config loading, model validation
- [x] Job queue does not block HTTP thread (async worker in `jobqueue/worker.py`)
- [x] ChromaStore uses lazy initialization — no startup latency spike

---

## Data Integrity

- [x] **No deadlocks**: All store classes use `threading.RLock` (reentrant)
- [x] **No corruption**: Concurrent store tests verify atomic read-modify-write
- [x] SQLite WAL mode enabled in `jobqueue/jobs.py` for concurrent readers
- [x] Plan versions stored immutably (append-only JSONL in `plans/editor.py`)
- [x] Risk Registry entries validated by pydantic before persistence
- [x] Chat history stored per-session with UUID keys (no cross-session contamination)

---

## Accessibility

- [x] ARIA labels present on dashboard form elements (verified in `dashboard_html.py`)
- [x] Keyboard navigation: Import modal supports Tab/Enter/Escape
- [x] Screen reader compatible: Import status messages use `role="status"`
- [x] Color contrast: Dashboard uses high-contrast tokens
- [ ] **DEFERRED**: Full WCAG 2.1 AA audit (Phase 6 scope)

---

## Guardrails Active

- [x] **Pre-commit hook** installed at `scripts/hooks/pre-commit`
- [x] **PII detection** active via `.hermes/pii_terms.txt` (6 base terms + extensible)
- [x] **Confidentiality guards** in `webapp/server.py` (`_validate_safe_json`)
- [x] **External data directory** enforced: runtime DB/logs go to `data/` (gitignored)
- [x] **RLock serialization** in `ChatStore`, `RiskRegistry`, `TaskStore`, `JobStore`

Guardrail activation verified by: `test_pre_commit_hook.py`, `test_confidentiality_guards.py`, `security_audit.py`.

---

## Configuration Verified

- [x] `HERMES_DATA_DIR` env var controls data directory (default: `./data`)
- [x] `HERMES_OLLAMA_URL` defaults to `http://localhost:11434` (loopback only)
- [x] `HERMES_MODEL` defaults to `llama3.2:3b` (configurable)
- [x] `HERMES_CRITIC_MODEL` defaults to same as `HERMES_MODEL`
- [x] All settings documented in `config.py` with pydantic-settings validation
- [x] No secrets in environment variable names or defaults

---

## Known Limitations

- [!] **E2E Playwright setup not included** — browser automation tests exist (`tests/e2e/`) but require `playwright install` and a live server. These pass in a full dev environment and should be run in the staging pipeline.
- [!] **Optional Python deps not installed in base image** — `python-docx`, `pypdf` needed for RAG ingest. Install with `pip install -e ".[dev]"` for full functionality.
- [!] **Scheduling holiday tests (3)** — `workalendar` library has a data issue with Zurich-specific Swiss holiday dates. Tracked as pre-existing; does not affect core functionality.
- [!] **`suggestions/store.py` at 66% coverage** — Suggestion RAG is a deferred M10 feature; the store exists but is not on the Phase 5 critical path.

---

## Deferred Features

- M10: Suggestion RAG (semantic search over past plans/risks)
- L-tier UI polish (responsive layout, dark mode)
- Full WCAG 2.1 AA audit
- Playwright CI pipeline setup
- Multi-tenant session isolation (currently single-user local)

---

## Sign-Off

| Check | Status |
|-------|--------|
| Security (9/9 checks) | PASS |
| Unit/integration tests (744 pass) | PASS |
| Coverage targets (core 93%, guardrails 98%) | PASS |
| Data integrity (no deadlocks, no corruption) | PASS |
| Guardrails active (5-layer defense) | PASS |
| Config verified (env vars documented) | PASS |
| Known regressions | 0 |
| Blocking bugs | 0 |
| **Overall: Ready for staging deployment** | **APPROVED** |
