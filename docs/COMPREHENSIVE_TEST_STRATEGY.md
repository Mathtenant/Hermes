# Hermes-Assistant Phase 5 — Comprehensive Test Strategy
## Sanity, Consistency, Unit, & E2E Testing Plan

**Status:** Planning complete | **Target:** 90%+ coverage, production-ready | **Timeline:** 4 weeks

---

## Executive Summary

Current test suite: **877 tests passing** (unit, integration, perf, security).

**New test tiers to add:** 
- **Sanity** (20–30 tests, <60s) — smoke/health checks, fail-fast gate
- **Consistency** (30–40 tests, <3 min) — invariant assertions (immutability, atomicity, concurrency)
- **Unit expansion** (877 → 930+) — edge cases, regressions, coverage gaps
- **E2E** (18 → 45 tests, ~30 min) — user journeys, browser automation

**Total new tests:** ~120 | **Total test suite:** ~1000 | **Runtime budget:** <5 min offline + <30 min staging

---

## Critical Corrections to Original Brief

### 1. No REST CRUD Endpoints for Risks/Plans
**Finding:** There are **zero** `/api/risks/*` or `/api/plans/*` HTTP routes.

**Impact:** The brief's sanity test `POST /api/risks/create returns 200` does not apply. Risks and plans are **library/store objects**, not REST resources.

**Solution:** Test CRUD via **in-process store access** (FastAPI TestClient doesn't require a live server):
```python
def test_risk_create_and_get(tmp_path):
    registry = RiskRegistry(str(tmp_path / "risks.db"))
    risk_id = registry.create(title="Test", severity="high")
    risk = registry.get(risk_id)
    assert risk.title == "Test"
```

The only mutating HTTP route is `POST /api/import/json` (for Copilot uploads) and chat routes.

### 2. RiskStatus Lifecycle & Missing `accepted_at` Timestamp
**Finding:** The model defines:
```python
class RiskStatus(str, Enum):
    open = "open"
    mitigated = "mitigated"
    accepted = "accepted"
    closed = "closed"
```

**Current gap:** `registry.accept()` sets `status=accepted` but does **not** set an `accepted_at` timestamp. Audit trails cannot record when/by-whom risks were signed off.

**Solution:** Coder task to add `accepted_at: datetime | None` field to `Risk` model and set it in `registry.accept()`. This enables:
- Compliance audit: "show all risks accepted on 2026-08-10"
- Consistency test: "accepted risk has acceptance_date"

### 3. E2E is Python Playwright (Not TypeScript)
**Finding:** `tests/e2e/` already uses Python Playwright with pytest integration:
```python
pytestmark = pytest.mark.e2e
def test_chat_collapse(page):
    await page.goto("http://localhost:8000")
    await page.click('[data-collapse-target="chat-panel"]')
```

**Solution:** Do **not** introduce TypeScript `@playwright/test`. Extend the existing Python suite. Avoids a second toolchain, fork in CI, and fixture duplication.

---

## Section 1: Testing Pyramid & Strategy

```
                    E2E (Python Playwright)
                   /                       \
                45–50 tests              ~30 min
              User journeys            (staging)
             /                           \
          Unit expansion (930+)        Consistency
         /     Edge/error/regression    (30–40)
        / Regression guards from audit  State machine
       /   ~90 min offline              Atomicity
      /                                 <3 min
  Sanity (20–30)
  <60s, fail-fast
  Health checks
```

| Tier | Target | Runtime | When | Coverage |
|------|--------|---------|------|----------|
| **Sanity** | 20–30 | <60s | Pre-commit + CI job 1 (gate) | N/A (tripwire) |
| **Consistency** | 30–40 | <3 min | Every push + pre-deploy | 100% of invariants |
| **Unit** | 930+ | <90s | Every push | 90% line on core 4 modules |
| **E2E** | 45–50 | <30 min | Staging only, nightly | All 7 user journeys |

### Why Each Tier Matters

**Sanity:** Catches "app didn't boot" / "SQLite locked" / "Ollama unreachable" in 60s. With 4 shared-connection RLock stores, a migration corruption or schema mismatch is the most common deploy failure.

**Consistency:** The real production risk. Verifies that:
- Plan versions are immutable (can't edit v1, only append v2)
- FK cascade actually deletes orphaned messages (SQLite footgun: `PRAGMA foreign_keys=ON` is per-connection)
- Import is atomic (partial failure → 0 rows written, not half-written)
- Risk lifecycle enforced (no illegal transitions like `closed → open`)
- Concurrent writes produce deterministic final state (RLock working)

**Unit:** Protects module internals. Expansion targets edge cases (empty inputs, boundary values, None), error paths, and one regression guard per audit fix.

**E2E:** Validates browser wiring (Q2 collapse animation end-state, import UI with validation messages, review "Apply" loop creating v2) that unit tests structurally cannot see.

---

## Section 2: Sanity Tests (New, 20–30 tests)

**File:** `tests/test_sanity.py`  
**Marker:** `sanity` (registered in `pyproject.toml`)  
**Run:** `pytest -m sanity` (CI job 1, <60s, blocks merge)  
**Fixture:** FastAPI `TestClient` (no live server needed)

### Endpoint Coverage
- `GET /api/health` → 200, contains expected keys
- `GET /api/dashboard` → 200, JSON body
- `GET /api/refresh` → 200 (or appropriate)
- `POST /api/import/json` with minimal Copilot v1 → 200 + summary
- `POST /api/import/json` with `{}` → 4xx structured error (not stack trace)
- Chat router: `POST /api/chat/message` → message object; `GET /api/chat/sessions` → list; `GET /api/chat/sessions/{id}` round-trip; `DELETE /api/chat/sessions/{id}` → 204

### Store CRUD (In-Process)
```python
def test_risk_registry_crud(tmp_path):
    registry = RiskRegistry(str(tmp_path / "r.db"))
    risk_id = registry.create(title="Test", severity="high")
    assert registry.get(risk_id).title == "Test"
    assert len(registry.list()) == 1

def test_plan_editor_version(tmp_path):
    editor = PlanEditor(str(tmp_path / "p.db"))
    plan_id = editor.create(title="v1", ...)
    v1 = editor.get(plan_id, version=1)
    editor.update(plan_id, ...)
    v2 = editor.get(plan_id, version=2)
    assert v1 != v2

def test_chat_session(tmp_path):
    store = ChatStore(str(tmp_path / "c.db"))
    session_id = store.create_session(project_id="proj1")
    session = store.get_session(session_id)
    assert session.project_id == "proj1"
```

### Config & Infrastructure
- `settings.data_dir` loads from env or defaults to `~/.hermes/data`
- Data dir exists and is writable
- RLock present on all 4 stores (grep `self._lock = threading.RLock()`)

### Success Criteria
✅ 100% pass, <60s, **zero flakes**, gates pre-commit + CI job 1

---

## Section 3: Consistency / Invariant Tests (New, 30–40 tests)

**Files:**
- `tests/test_invariants_plans.py` — immutability
- `tests/test_invariants_risks.py` — lifecycle + gaps
- `tests/test_invariants_chat.py` — isolation + FK cascade
- `tests/test_invariants_import.py` — atomicity + M2 idempotency
- `tests/test_invariants_concurrency.py` — 20-thread RLock correctness

**Run:** `pytest tests/test_invariants_*.py` (<3 min, every push)

### test_invariants_plans.py

```python
def test_plan_versions_immutable(tmp_path):
    """v1 snapshots are byte-identical after v2 created."""
    editor = PlanEditor(str(tmp_path / "p.db"))
    plan_id = editor.create(title="Plan", ...)
    v1_original = editor.get(plan_id, version=1)
    
    editor.update(plan_id, ...)
    v1_after = editor.get(plan_id, version=1)
    
    assert v1_original == v1_after  # unchanged
    assert editor.get(plan_id, version=2) != v1_original
```

### test_invariants_risks.py

```python
def test_risk_lifecycle_legal_transitions(tmp_path):
    """Risk status transitions follow open→mitigated→accepted→closed."""
    registry = RiskRegistry(str(tmp_path / "r.db"))
    risk_id = registry.create(title="Test", severity="high")
    
    assert registry.get(risk_id).status == RiskStatus.open
    registry.mitigate(risk_id)
    assert registry.get(risk_id).status == RiskStatus.mitigated
    registry.accept(risk_id)
    assert registry.get(risk_id).status == RiskStatus.accepted
    
    # Illegal: closed → open (currently allowed, should be guarded)
    registry.close(risk_id)
    with pytest.raises(ValueError):  # xfail until coder task lands
        registry.update(risk_id, status=RiskStatus.open)

def test_export_public_omits_confidential(tmp_path):
    """Export filters confidential=True risks and internal fields."""
    registry = RiskRegistry(str(tmp_path / "r.db"))
    registry.create(title="Public", confidential=False)
    registry.create(title="Secret", confidential=True)
    
    public = registry.export_public()
    assert any(r.title == "Public" for r in public)
    assert not any(r.title == "Secret" for r in public)
```

### test_invariants_chat.py

```python
def test_chat_session_isolation(tmp_path):
    """Messages from session A never leak to session B."""
    store = ChatStore(str(tmp_path / "c.db"))
    session_a = store.create_session("proj1")
    session_b = store.create_session("proj1")
    
    store.add_message(session_a, ChatRole.user, "Hello A")
    store.add_message(session_b, ChatRole.user, "Hello B")
    
    msgs_a = store.list_messages(session_a)
    msgs_b = store.list_messages(session_b)
    
    assert len(msgs_a) == 1 and msgs_a[0].content == "Hello A"
    assert len(msgs_b) == 1 and msgs_b[0].content == "Hello B"

def test_chat_fk_cascade_delete(tmp_path):
    """Delete session → messages + actions deleted (FK cascade)."""
    store = ChatStore(str(tmp_path / "c.db"))
    session_id = store.create_session("proj1")
    store.add_message(session_id, ChatRole.user, "Test")
    
    assert len(store.list_messages(session_id)) == 1
    
    store.delete_session(session_id)
    
    assert len(store.list_messages(session_id)) == 0
```

### test_invariants_import.py

```python
def test_import_atomicity_partial_failure(tmp_path):
    """Import 10 risks where #5 fails → 0 rows written (all-or-nothing)."""
    registry = RiskRegistry(str(tmp_path / "r.db"))
    payload = [
        {"title": f"Risk {i}", "severity": "high"} for i in range(1, 6)
    ] + [
        {"title": "Bad Risk", "severity": "invalid"}  # Fails
    ] + [
        {"title": f"Risk {i}", "severity": "high"} for i in range(7, 11)
    ]
    
    result = import_risks(registry, payload)
    assert result.created == 0  # all-or-nothing: 0 created
    assert len(registry.list()) == 0  # DB untouched

def test_m2_import_idempotency_external_ref(tmp_path):
    """Re-import same Copilot JSON twice → no duplicates (dedup on external_ref)."""
    payload = [
        {"title": "Risk A", "external_ref": "cop-123", "severity": "high"},
        {"title": "Risk B", "external_ref": "cop-456", "severity": "high"},
    ]
    
    registry = RiskRegistry(str(tmp_path / "r.db"))
    import_risks(registry, payload)
    assert len(registry.list()) == 2
    
    import_risks(registry, payload)
    assert len(registry.list()) == 2  # Still 2, not 4
    
    # Modify and re-import: row is updated
    payload[0]["title"] = "Risk A (updated)"
    import_risks(registry, payload)
    assert registry.get_by_external_ref("cop-123").title == "Risk A (updated)"
```

### test_invariants_concurrency.py

```python
def test_concurrent_writes_deterministic(tmp_path):
    """20 threads calling store methods → final state deterministic, no corruption."""
    from concurrent.futures import ThreadPoolExecutor
    
    registry = RiskRegistry(str(tmp_path / "r.db"))
    results = []
    
    def create_risk(i):
        risk_id = registry.create(title=f"Risk {i}", severity="high")
        return risk_id
    
    with ThreadPoolExecutor(max_workers=20) as ex:
        results = list(ex.map(create_risk, range(20)))
    
    assert len(set(results)) == 20  # All IDs unique
    assert len(registry.list()) == 20  # No duplicates, no loss
```

### Success Criteria
✅ 100% pass, <3 min, **all invariants verified**

---

## Section 4: Unit Test Expansion (877 → 930+)

**Target:** Add 50+ tests to fill edge/error/regression gaps. Do **not** rewrite existing; extend.

### Per-Module Gap Analysis

**`risks/registry.py`:**
- `list()` with filter+sort: `list(source="review", sort_by="severity")` etc.
- `auto_create` on empty/None/gibberish text
- `RiskNotFoundError` on `update`/`accept` of missing ID
- Concurrent `assign_owner` calls (pairs with concurrency invariant test)

**`plans/editor.py`:**
- Diff generation: added/changed/removed `Outcome` fields
- `PlanVersionNotFoundError` on `get(plan_id, version=999)`
- `reorder` with duplicate/invalid phase IDs
- Version immutability via direct SQL (no UPDATE on existing rows)

**`chat/service.py` + `router.py`:**
- Intent classification boundary strings ("wat", "???", empty string)
- `ResponseFormatter.detect_language` for de/en edge cases
- `ConfidentialityGuardError` in `chat_api.py:40` execution path
- Oversized message (>2000 chars) handling
- Empty message handling

**`webapp/import_adapters.py`:**
- Unknown `schema_version` → clear `UnsupportedSchema` error
- Enum translation: `tief/mittel/hoch` → 1-5 integer
- Tree flattening: WBS with deep nesting, `parent_ref` cycles, missing nodes

### Regression Guards (From AUDIT_REMEDIATION_SUMMARY.md)
Each Critical/High fix gets a unit test that **would have caught the bug**:

| Fix | Regression Test |
|-----|-----------------|
| C1 (Copilot adapter) | `test_adapt_project_state_v1_schema_maps_enums` (exists) |
| C2 (XSS) | `test_import_error_escaped_in_html` (exists) |
| C3 (RLock) | `test_concurrent_writes_deterministic` (concurrency tier) |
| H1 (Guard before persist) | `test_confidentiality_violation_no_persist` (new) |
| H5 (Atomic import) | `test_import_atomicity` (consistency tier) |
| M2 (Idempotency) | `test_m2_idempotency_external_ref` (consistency tier) |

**Coverage gate:** `pytest --cov=hermes_assistant.risks --cov=hermes_assistant.plans --cov=hermes_assistant.chat --cov=hermes_assistant.webapp.import_json --cov-fail-under=90`

### Success Criteria
✅ 930+ tests total, ✅ 90%+ line coverage on 4 core modules, ✅ Every audit fix has a guard test

---

## Section 5: E2E Tests (Extend Python Playwright, 18 → 45)

**Prerequisites:** Playwright already installed and configured (`pytestmark = pytest.mark.e2e`, socket probe).  
**New files:**
- `test_e2e_chat_flow.py`
- `test_e2e_risk_lifecycle.py`
- `test_e2e_plan_editing.py`
- `test_e2e_import.py`
- `test_e2e_review_loop.py`
- `test_e2e_a11y.py`
- `test_e2e_errors.py`

**Run:** `pytest -m e2e` (staging only, ~30 min)

### Journey 1: Chat Conversation Flow

```python
@pytest.mark.e2e
def test_chat_sends_message_and_receives_response(page):
    page.goto("http://localhost:8000")
    page.fill('#chat-input', 'Hello')
    page.click('#send-btn')
    response = page.wait_for_selector('.message.assistant')
    assert response.is_visible()

@pytest.mark.e2e
def test_chat_panel_collapse_animates(page):
    """Q2 fix verification: collapse button works, animation smooth."""
    page.goto("http://localhost:8000")
    panel = page.locator('#chat-panel')
    collapse_btn = page.locator('[data-collapse-target="chat-panel"]')
    
    # Initial height
    initial_height = panel.bounding_box()['height']
    assert initial_height > 100
    
    # Collapse
    collapse_btn.click()
    page.wait_for_load_state('networkidle')
    
    # End height (should be small, header only)
    final_height = panel.bounding_box()['height']
    assert final_height < 100
    assert collapse_btn.get_attribute('aria-expanded') == 'false'

@pytest.mark.e2e
def test_chat_session_isolation(page, browser):
    """Two browser sessions don't leak messages."""
    page1 = page
    page2 = browser.new_page()
    
    page1.goto("http://localhost:8000")
    page2.goto("http://localhost:8000")
    
    page1.fill('#chat-input', 'User 1 message')
    page1.click('#send-btn')
    
    # page2 should not see the message
    messages_page2 = page2.locator('.message.user')
    assert messages_page2.count() == 0
```

### Journey 2: Risk Lifecycle

```python
@pytest.mark.e2e
def test_risk_lifecycle_in_ui(page):
    """Create → assign → accept → verify UI reflects state."""
    page.goto("http://localhost:8000")
    
    # Chat: "Create a risk called Data Breach"
    page.fill('#chat-input', 'Create a risk called Data Breach')
    page.click('#send-btn')
    page.wait_for_selector('.message.assistant')
    
    # Navigate to Risk Registry (implied: UI has a link)
    page.click('text=Risks')
    risk_row = page.locator('text=Data Breach')
    assert risk_row.is_visible()

@pytest.mark.e2e
def test_export_omits_confidential_risks(page):
    """Exported risks don't include confidential=True."""
    # Requires test fixture with a confidential risk in DB
    # Then export and verify it's omitted
```

### Journey 3: Plan Editing

```python
@pytest.mark.e2e
def test_plan_version_history(page):
    """Save v1, edit→v2, history shows both with diffs."""
    page.goto("http://localhost:8000")
    page.click('text=Edit Plan')
    
    # v1 exists
    page.click('text=History')
    versions = page.locator('.version-item')
    assert versions.count() >= 1
    
    # Goto edit, add outcome, save v2
    page.click('text=Add Outcome')
    page.fill('input[placeholder="Outcome title"]', 'New outcome')
    page.click('text=Save Version')
    
    # v2 appears
    versions = page.locator('.version-item')
    assert versions.count() >= 2
```

### Journey 4: Copilot Import (M2 Idempotency Check)

```python
@pytest.mark.e2e
def test_import_copilot_json_idempotent(page):
    """Import same Copilot JSON twice → no duplicates."""
    page.goto("http://localhost:8000")
    page.click('text=Import JSON')
    
    # Step 1: see prompt
    prompt_text = page.locator('.copilot-prompt').inner_text()
    assert 'Copilot' in prompt_text
    
    # Step 2: paste JSON
    page.fill('textarea[placeholder="Paste JSON"]', COPILOT_V1_JSON)
    page.click('text=Import')
    
    result1 = page.locator('.import-result')
    created1 = int(result1.get_attribute('data-created'))
    
    # Re-import same JSON
    page.click('text=Import JSON')
    page.fill('textarea[placeholder="Paste JSON"]', COPILOT_V1_JSON)
    page.click('text=Import')
    
    result2 = page.locator('.import-result')
    created2 = int(result2.get_attribute('data-created'))
    
    # No new rows created (M2 idempotency)
    assert created2 == 0
```

### Journey 5: Review Feedback → Apply Suggestion

```python
@pytest.mark.e2e
def test_review_feedback_apply_suggestion(page):
    """Review fails, suggestion shown, apply creates v2."""
    # Prerequisite: test fixture has a plan + review that failed
    # This test may require mock server hooks or fixtures
```

### Journey 6: Accessibility

```python
@pytest.mark.e2e
def test_keyboard_navigation_only(page):
    """Tab through all controls, Enter activates, no mouse needed."""
    page.goto("http://localhost:8000")
    
    # Tab to chat input
    for _ in range(3):
        page.press('Tab')
    
    page.fill('#chat-input', 'Hello')
    page.press('Enter')
    
    # Message sent without clicking
    assert page.locator('.message.user:has-text("Hello")').is_visible()

@pytest.mark.e2e
def test_aria_labels_present(page):
    """All interactive elements have aria-label or <label>."""
    page.goto("http://localhost:8000")
    
    collapse_btn = page.locator('[data-collapse-target="chat-panel"]')
    assert collapse_btn.get_attribute('aria-label')
    
    send_btn = page.locator('#send-btn')
    assert send_btn.get_attribute('aria-label')
```

### Journey 7: Error Handling

```python
@pytest.mark.e2e
def test_invalid_json_shows_validation_errors(page):
    """Invalid JSON import shows field-level errors, not stack trace."""
    page.goto("http://localhost:8000")
    page.click('text=Import JSON')
    page.fill('textarea', '{"risks": [{"severity": "invalid"}]}')
    page.click('text=Import')
    
    error = page.locator('.import-error')
    assert error.is_visible()
    assert 'severity' in error.inner_text()
    assert 'Traceback' not in error.inner_text()
```

### Anti-Flake Rules (Enforce in Review)

✅ Use explicit waits, **never** `time.sleep()`  
✅ Assert end-state, not intermediate animations: `expect(panel).to_be_hidden()` not `wait_for_timeout(500)`  
✅ Isolate DB: each run gets a fresh `tmp_path` data dir  
✅ Capture traces on failure: `pytest --tracing retain-on-failure`  
✅ Screenshot on error for debugging

### Success Criteria
✅ 45–50 tests, ✅ 100% pass on staging, ✅ All 7 journeys covered, ✅ Zero flakes (10 runs = 10 passes)

---

## Section 6: Implementation Roadmap (4 Weeks)

**Week 1 — Sanity Tests**
- File: `tests/test_sanity.py` + register `sanity` marker
- Dispatch: Coder task for sanity tests
- Gate: Pre-commit + CI job 1 (fail-fast)
- ROI: Cheapest, most immediate value

**Week 2 — Consistency/Invariant Tests**
- Files: `test_invariants_*.py` (5 files, 30–40 tests)
- Dispatch: Coder task for invariants
- Plus: Coder task to add `accepted_at` field + risk lifecycle guard (these flip xfail tests to pass)
- Gate: CI job 2, every push

**Week 3 — Unit Expansion + Coverage Gate**
- Add 50+ unit tests (edge cases, regressions, error paths)
- Enforce `--cov-fail-under=90` on core 4 modules
- Backfill regression guards from audit fixes
- Gate: CI job 2

**Week 4 — E2E Expansion**
- Extend Python Playwright to 45 tests (7 journeys)
- Add `axe-core` a11y checks (automated, runs in CI)
- Staging CI job with trace retention
- Gate: Nightly + pre-release

---

## Section 7: Tools & Infrastructure

**Already present:**
- `pytest`, `pytest-cov`, `pytest-asyncio`
- FastAPI + `httpx` TestClient
- Python Playwright (no TypeScript)
- Markers: `e2e`, `integration`
- Fixtures: offline mocking in `conftest.py`

**Add:**
- `sanity` marker (register in `pyproject.toml`)
- `pytest-xdist` (optional dependency, `--dist loadscope` only, avoid SQLite contention)
- `axe-core-python` or CDN-injected axe for a11y (lighter than NVDA, runs in CI)

**Do NOT add:**
- TypeScript Playwright
- Selenium, Cypress, or other browser tools
- Remote service mocking (keep it local)

**CI Shape:**
```
Job 1: pytest -m sanity (fail-fast, <60s)
Job 2: pytest -m "not e2e and not integration" (unit+invariants, <90s)
Job 3: staging pytest -m e2e (nightly + pre-release, ~30 min, traces)
```

---

## Section 8: Known Risks & Mitigations

**Flaky E2E tests**
- Risk: `wait_for_timeout(500)` on animation is fragile
- Mitigation: Use explicit waits (`expect(...).to_be_hidden()`) + `expect(...).to_have_bounding_box({height: <50})`

**SQLite FK cascade false confidence**
- Risk: `PRAGMA foreign_keys=ON` must be set per-connection; the test could pass on its own connection but fail in production
- Mitigation: Assert actual row deletion in DB, not trust schema; use store's connection fixture

**Name collision with existing `test_consistency.py`**
- Risk: Existing file tests MECE (multi-model) consistency, new tests assert data-integrity invariants — confusion
- Mitigation: Use `test_invariants_*.py` filenames only

**xfail strict tests blocking pre-merge**
- Risk: `xfail(strict=True)` for the risk-lifecycle guard will fail until the coder task lands
- Mitigation: File the coder task immediately; keep risk-lifecycle xfail tests separate so other invariants don't block

**Coverage gate on wrong scope**
- Risk: Global `--cov-fail-under=90` will fail because TUI/RAG/agents dilute it
- Mitigation: Scope gate to 4 core modules only: `--cov=hermes_assistant.risks --cov=hermes_assistant.plans --cov=hermes_assistant.chat --cov=hermes_assistant.webapp.import_json --cov-fail-under=90`

---

## Section 9: Coder Task Handoffs

```
TASK 1: SANITY TESTS
Files: tests/test_sanity.py, pyproject.toml
Implement 20-30 sanity-marked smoke tests:
- Endpoint coverage (/api/health, /dashboard, /refresh, /import/json, chat routes)
- Store CRUD (RiskRegistry, PlanEditor, ChatStore via tmp_path DBs)
- Config loading, data dir, RLock presence
- Target: <60s, 100% pass, gates pre-commit + CI job 1
```

```
TASK 2: INVARIANT TESTS
Files: tests/test_invariants_plans.py, tests/test_invariants_risks.py, tests/test_invariants_chat.py, tests/test_invariants_import.py, tests/test_invariants_concurrency.py
Implement 30-40 consistency tests:
- Plan immutability (v1 unchanged after v2 created)
- Risk lifecycle with illegal-transition xfail(strict=True) guards
- Chat isolation + FK cascade (actual row deletion verification)
- Import atomicity (partial failure → 0 rows)
- M2 idempotency (re-import dedup on external_ref)
- 20-thread RLock determinism
- Target: <3 min, 100% pass, runs every push
```

```
TASK 3: MODEL + GUARD FIX
Files: src/hermes_assistant/risks/model.py, src/hermes_assistant/risks/registry.py
Add accepted_at timestamp and risk-lifecycle state-machine guard:
- Add accepted_at: datetime | None to Risk model
- Set accepted_at in registry.accept()
- Add legal-transition checks to update/accept/mitigate/close (raise ValueError on illegal transitions)
- Context: Flips xfail(strict=True) lifecycle tests to pass
```

```
TASK 4: UNIT EXPANSION
Files: tests/test_*.py (existing modules)
Add 50+ unit tests to fill edge/error/regression gaps:
- risks/registry.py: list(filter/sort), auto_create edge cases, RiskNotFoundError
- plans/editor.py: diff generation, version not found, reorder invalid IDs
- chat/service.py + router.py: classification boundaries, language edge cases, oversized messages
- webapp/import_adapters.py: unknown schema, enum translation, tree flattening
- Every audit fix gets a regression guard
- Target: 930+ total, 90%+ coverage on 4 core modules
```

```
TASK 5: E2E EXPANSION
Files: tests/e2e/test_e2e_*.py (7 new files)
Extend Python Playwright to 45–50 tests (7 journeys):
- Chat flow + Q2 collapse animation
- Risk lifecycle + export filter
- Plan editing + version history
- Copilot import + M2 re-import idempotency
- Review feedback loop
- Keyboard + ARIA a11y
- Error messages (no stack traces)
- Target: <30 min on staging, 100% pass, zero flakes (10 runs stable)
```

---

## Timeline & Success Criteria

| Week | Deliverable | Success |
|------|-------------|---------|
| 1 | Sanity tests | <60s, gates CI |
| 2 | Invariant tests + model fix | <3 min, 100% pass, xfails → pass |
| 3 | Unit expansion + coverage | 930+ tests, 90%+ coverage |
| 4 | E2E expansion | 45–50 tests, <30 min, staging |

**Final state:** ~1000 tests, <5 min offline + <30 min staging, 90%+ coverage, zero regressions, production-ready.

---

*Document date: 2026-08-10*  
*Architect: Claude Opus 4.8*  
*Status: Ready for implementation phase*
