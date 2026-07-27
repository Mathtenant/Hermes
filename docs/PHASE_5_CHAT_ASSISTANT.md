# Phase 5: Chat Assistant

## Overview
A text-based conversational interface for hermes-assistant. Users interact with
the project (risks, tasks, plans, reviews) using natural language, and the
assistant classifies each message, executes the matching action, and replies in
prose. All inference is local (Ollama); no data leaves the machine.

## Architecture
- **IntentRouter** (`chat/router.py`) — classifies a message into one of eight
  intents using the ROUTER model (`qwen3:4b`) via grammar-constrained structured
  output. The LLM client is duck-typed (`LLMClient` Protocol) for test injection.
- **ActionExecutor** (`chat/executor.py`) — dispatches an intent to a concrete
  side effect against the Risk Registry, Task Store, and Plan Editor. Every
  handler returns a JSON-serialisable dict; errors are captured, not raised.
- **ChatService** (`chat/service.py`) — orchestrates one turn end to end:
  classify → execute (or fall back) → format → persist → suggest. Intent
  classification is wrapped so an unavailable ROUTER model degrades to a safe
  `answer_question` fallback rather than failing the request.
- **ChatStore** (`chat/store.py`) — WAL-mode SQLite persistence of sessions,
  messages, and actions with `ON DELETE CASCADE`. Opened with
  `check_same_thread=False` so FastAPI's threadpool workers can use it.
- **ResponseFormatter** (`chat/service.py`) — renders executor result dicts into
  natural-language replies.
- **prompts.py** — the router and answer system prompts plus `build_context_block`.

## API Endpoints (`webapp/chat_api.py`)
- `POST /api/chat/message` — send a message, get the assistant response.
- `GET /api/chat/sessions` — list sessions (optional `project_id` filter).
- `GET /api/chat/sessions/{id}` — session plus full message history.
- `DELETE /api/chat/sessions/{id}` — delete a session (cascades messages/actions).

All responses pass through a confidentiality guard; blocking work runs in a
thread pool. Input is validated (message 1–2000 chars, `project_id` required).

## Frontend (`webapp/static/chat.js`)
A self-contained, framework-free widget mounted into `#chat-app` in
`index.html`. Fixed bottom-right, collapsible, with user/assistant bubbles,
suggestion buttons, a typing indicator, Enter-to-send, and inline error display.

## Intents
`create_risk`, `create_task`, `list_risks`, `show_plan`, `review_status`,
`run_review`, `answer_question`, `smalltalk`.

## Testing
- 13 unit tests — `ChatStore` (Phase 5.1, pre-existing).
- 11 unit tests — `IntentRouter` (`test_chat_router.py`).
- 15 unit tests — `ActionExecutor` (`test_chat_executor.py`).
- 10 unit tests — `ChatService` / `ResponseFormatter` (`test_chat_service.py`).
- 20 API integration tests — endpoints, isolation, guard (`test_chat_integration.py`).
- 2 performance tests — orchestration + DB latency (`perf/test_chat_latency.py`).
- 15 E2E browser tests — `e2e/test_chat_ui.py`, marked `e2e`; skipped unless
  Playwright and a live server on `:8000` are present.

## Security
- Confidentiality guard on every dict API response (forbidden field names,
  `internal_*` / `confidential_*` patterns, absolute paths, emails).
- Input validation at the API boundary (length, required fields).
- `list_risks` uses `export_public()`, excluding confidential risks.
- All actions are persisted to `chat_actions` for an audit trail.

## Performance
- Orchestration overhead (excluding LLM): well under 100 ms per turn.
- SQLite list queries: single-digit milliseconds.
- Message latency in production is dominated by ROUTER inference (~15 tok/s).

## Notes & Follow-ups
- The router passes its system prompt as a `system=` kwarg, matching the
  injected-fake contract used in unit tests. The production `OllamaClient`
  should carry the system prompt as a `system`-role message; until then, the
  service's graceful-degradation path returns a safe fallback reply.
- Future: streaming responses, per-session rate limiting, richer context
  hydration (live risks/plan/tasks). Voice I/O is explicitly out of scope.
