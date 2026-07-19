# HERMES Web Dashboard (Phase 4)

A locally-hosted, single-page web dashboard that provides visual access to
all HERMES project data. Replaces the TUI as the primary interface for
day-to-day use.

## Quick Start

```bash
bash scripts/start-web.sh
# Open browser: http://localhost:8000
```

## Architecture

```
Browser (Vue 3 + Tailwind CDN)
        │  fetch /api/dashboard
        ▼
FastAPI server (hermes_assistant.webapp.server)
        │  load_dashboard_data() [reuse from dashboard_html.py]
        │  _validate_safe_json()  [confidentiality guard]
        ▼
SQLite task/job stores + schedule.json files
```

### Backend — `src/hermes_assistant/webapp/server.py`

| Endpoint | Method | Description |
|---|---|---|
| `/api/health` | GET | Health check; returns `{"status":"ok","timestamp":"…"}` |
| `/api/dashboard` | GET | Full DashboardData JSON (all projects) |
| `/api/dashboard?project_id=X` | GET | Scoped DashboardData for project X |
| `/api/refresh` | GET | Same as `/api/dashboard` — triggers fresh disk read |
| `/` and `/*` | GET | Serves `index.html` (SPA fallback) |
| `/static/*` | GET | CSS, JS, HTML static assets |

### Frontend — `src/hermes_assistant/webapp/static/`

| File | Purpose |
|---|---|
| `index.html` | SPA shell; loads Vue 3 + Tailwind from CDN |
| `style.css` | CSS custom properties, dark/light theme, layout |
| `components.js` | Shared WBS components (`WbsNodeItem`, `WbsTab`) |
| `screens.js` | Screen components for all 4 views |
| `app.js` | Root app, global state, keyboard shortcuts, polling |

## Screens

### 1 — Projects
Sortable table of all project directories. Click any row to drill into
Project Detail. Columns: Project ID, Label, Timeline count, Pendenzen, Reviews.

### 2 — Project Detail
Three tabs for the selected project:
- **Timeline** — chronological list of schedule items, colour-coded by status
  (green = closed, red = blocked, grey = future)
- **Kanban** — To Do / Blocked / Done columns with card click-to-expand
- **WBS** — collapsible tree (Expand all / Collapse all), status icons
  (✓ closed, ! blocked, ○ open)

### 3 — Pendenzen
Filterable table: source (manual/review/decision/meeting), priority
(blocker/high/medium/low), status (open/closed/blocked). Sorted by priority
rank by default.

### 4 — Reviews
Completed review jobs. Verdict colour coding: green (pass), amber
(pass\_with\_comments), red (fail). Click any row to open the detail modal.

## Keyboard Shortcuts

| Key | Action |
|---|---|
| `1` | Projects screen |
| `2` | Project detail |
| `3` | Pendenzen |
| `4` | Reviews |
| `r` | Refresh data |
| `d` | Toggle dark / light theme |
| `?` | Show / hide keyboard help |
| `Esc` | Close modal |

Theme preference is persisted in `localStorage`.

## Security

- **Same-origin only** — no CORS headers; browser enforces SOP.
- **CSP headers** on every response: `default-src 'none'`; only `'self'` and
  HTTPS (CDN) sources allowed for scripts and styles.
- **Confidentiality guard** — every API response is validated by
  `_validate_safe_json()` before delivery. Forbidden fields (`raw_notes`,
  `evidence_quote`, `rationale`, `assumptions`, etc.) trigger HTTP 500.
- **Pydantic `extra="forbid"`** on all view models prevents accidental
  confidential-field inclusion at the data layer.
- **No authentication** — trusted company LAN assumption (Phase 5 adds SSO).
- **Localhost only** — server binds to `127.0.0.1` by default.

## Installing Dependencies

```bash
# The webapp extra pulls in FastAPI + uvicorn:
pip install -e ".[webapp]"
```

The `dev` extra already includes FastAPI and httpx for testing.

## Running Tests

```bash
# Unit + integration tests (no browser needed):
pytest tests/test_webapp_endpoints.py tests/test_webapp_e2e.py -v

# Full suite:
pytest -q
```

## Company Network Deployment

For deployment on an internal server (not localhost), change the bind address:

```bash
uvicorn hermes_assistant.webapp.server:app --host 0.0.0.0 --port 8000
```

Add a reverse proxy (nginx/Caddy) for TLS termination if needed. No
additional configuration is required — the CSP policy uses `https:` as a
scheme-only allowlist, which works behind any HTTPS proxy.
