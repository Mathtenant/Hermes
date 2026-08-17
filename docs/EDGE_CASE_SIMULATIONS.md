# Edge-Case Simulation Suite (S1-S10)

`tests/sim/` is a dedicated fault-injection and load-simulation suite,
separate from the unit/integration/e2e suites. It exercises concurrency
races, on-disk corruption, partial/silent failures, slow or hung Ollama
calls, boundary conditions, replay idempotency, and resource exhaustion /
long-running accumulation against the SQLite-backed stores (`RiskRegistry`,
`PlanEditor`, `TaskStore`, `ChatStore`, `JobStore`) and the JSON import
pipeline (`webapp/import_json.py`).

No test in this suite touches a live Ollama service or `data/risks.db`:
every store is opened against `tmp_path`, and every LLM call is
monkeypatched at the transport layer (`requests.post`) or duck-typed away
with a fake client (mirroring the existing `tests/test_critic.py` /
`tests/test_queue.py` patterns).

## Layout

| File | Purpose |
|---|---|
| `tests/sim/faults.py` | Fault injection toolkit: barrier-synchronised thread runners, on-disk corruption helpers (`corrupt_wal`, `truncate_file`, `plant_stale_lock`), the `flaky()` nth-call-fails decorator, and `raw_conn()` for out-of-band, lock-bypassing SQLite inspection. |
| `tests/sim/snapshots.py` | `snapshot()` (checksummed table fingerprints, `updated_at` excluded), `reconcile()` (row-count-delta diffing between two snapshots), and `assert_invariants()` (re-derives enum/range/timestamp/FK/version-contiguity rules directly from the raw table, independent of the store's own guards). |
| `tests/sim/test_sim_p0.py` | S1-S3: correctness gaps under real concurrency. |
| `tests/sim/test_sim_faults.py` | S4, S5, S6, S8, S10: corruption recovery, cross-entity partial failure, slow/hung Ollama, boundary conditions, replay idempotency. |
| `tests/sim/test_sim_load.py` | S7, S9 (marked `slow`): resource exhaustion and long-running-accumulation soak proxies. |

## Simulations

- **S1 — cross-connection import-vs-live race.** A live `RiskRegistry`
  connection and a separate connection opened internally by
  `import_payload()` hammer the same `risks.db` file at the same instant
  (barrier-synchronised): 200 live creates racing a 1000-row import. Expected
  to **pass** — WAL + `busy_timeout` + per-instance `RLock` is sufficient to
  serialise two independent connections at the SQLite level.

- **S2 — plan version collision (`xfail`).** Two independent `PlanEditor`
  connections (or a live connection racing a batched plan import) update the
  same `plan_id` concurrently. `PlanEditor._next_version()` reads
  `MAX(version)+1` with no cross-connection coordination, so two connections
  can compute the same next version and race to insert it — one loses with a
  `sqlite3.IntegrityError`. Marked `xfail` pending a D-decision on
  cross-connection version atomicity; the assertions encode the desired
  behaviour (no collision), not the observed one.

- **S3 — closed-risk resurrection via re-import (`xfail`).**
  `RiskRegistry.update()` enforces the D5 lifecycle policy (`closed` is
  terminal), but `_import_risks`'s pass-2 write path bypasses the store's
  public API with a raw `INSERT OR REPLACE`, so a closed risk re-imported
  with `status: "open"` is silently resurrected. Marked `xfail` pending a
  D-decision on enforcing lifecycle transitions on the import path too.

- **S4 — corruption recovery (3 variants).** A corrupted `-wal` sidecar, a
  truncated main db file, and a stale/corrupt `-shm` file. Expected: WAL
  corruption and stale-shm degrade gracefully (silent data loss is
  acceptable; a crash is not — and severe WAL corruption may legitimately
  surface as a clean `sqlite3.DatabaseError` instead), while a truncated main
  file always raises a clear, typed `DatabaseError`.

- **S5 — cross-entity partial failure.** Risks import commits in a single
  transaction; plans/pendenzen import via sequential public-API calls with
  no surrounding transaction (documented in `import_json.py`'s module
  docstring). A fault injected into the second of three plans confirms:
  risks (an independent, already-committed batch) are unaffected; the first
  plan (committed before the failure) stays committed; the failing and
  never-attempted plans are absent.

- **S6 — slow/hung Ollama (3 variants).** High-latency-but-successful calls
  are traced with accurate latency; a hung connection (`ReadTimeout`)
  surfaces as a typed `OllamaTimeoutError` and is traced as a failure; 20
  concurrent `chat()` calls against a backend that can only serve 4 at a
  time all complete without deadlock or starvation.

- **S8 — boundary conditions.** Empty batch, single item, a 10,000-character
  title (exact round-trip), a batch at the documented 10,000-item cap
  (succeeds), a batch of 10,001 items (rejected), a zero-`effort_days`
  milestone (clamped to a 1-working-day minimum, never zero/negative), and a
  pathologically deep JSON array (`json.loads` raises a catchable
  `RecursionError`/`ValueError`, never crashes the process).

- **S10 — replay idempotency.** The same mixed risks/plans/pendenzen
  payload imported 10 times: first import creates, all nine replays report
  pure updates with zero new rows; final state has exactly one risk (with a
  single, non-duplicated `external_ref`), one plan (with 10 versions — each
  import legitimately bumps the version), and one pendenz.

- **S7 — resource exhaustion (`slow`).** 100k risks (10× 10k-item batches)
  listed in full; a single plan with 10,000 items; 1000 concurrent chat
  message writes; a 10k-row import repeated three times into fresh
  databases with `tracemalloc` peaks compared across iterations as a
  leak canary. All assertions use deliberately generous memory/time
  envelopes (tight enough to catch a real blow-up on a 16 GB M4 Air, loose
  enough not to be flaky across machines/CI).

- **S9 — long-running accumulation (`slow`, soak proxy).** 10,000 messages
  accumulated in one chat session; 100 versions of one plan (diffed
  end-to-end); 50 review jobs drained by 8 concurrent worker threads against
  one `JobStore` (each worker owns its own connection to the shared db file,
  since `JobStore` — unlike the other stores — does not open with
  `check_same_thread=False`), verifying atomic claim semantics hold under
  real thread concurrency with no double-processing and no lost jobs.

## Running

```bash
# Per-PR: fast suite only (S1, S4-S6, S8, S10; S2/S3 xfail)
pytest tests/sim/ -v --tb=short -m "not slow"

# Nightly: full suite including S7/S9 resource & soak simulations
pytest tests/sim/ -v --tb=short
```

`slow` and `serial` markers are registered in `pyproject.toml`. `serial`
flags simulations with heavy shared-resource usage (large SQLite files,
sustained thread pools) that should not be run in parallel with other `slow`
tests under a parallelised runner (e.g. pytest-xdist).
