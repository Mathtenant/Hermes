# HERMES Assistant — Deployment Guide

Version: Phase 5 (Text-Based Chat)  
Platform: macOS 14+ / Linux (Ubuntu 22.04+)  
Minimum RAM: 8 GB (16 GB recommended for local LLM)

---

## Prerequisites

| Dependency | Version | Notes |
|-----------|---------|-------|
| Python | 3.11+ | `python3.11 --version` |
| Ollama | 0.3+ | Must be running before starting HERMES |
| RAM | 16 GB | 8 GB minimum; 16 GB recommended for `llama3.2:3b` |
| Disk | 10 GB free | Model weights (~2 GB) + data dir |
| `git` | Any | For clone and hook activation |

### Install Ollama

```bash
# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.com/install.sh | sh

# Pull the default model
ollama pull llama3.2:3b

# Verify it runs
ollama run llama3.2:3b "Hello"
```

---

## Installation

### 1. Clone the Repository

```bash
git clone <repo-url> hermes-assistant
cd hermes-assistant
```

### 2. Run the Bootstrap Script

```bash
bash scripts/bootstrap.sh
```

This script:
- Creates and activates a Python virtual environment (`.venv/`)
- Installs all dependencies: `pip install -e ".[webapp,dev]"`
- Creates the data directory: `~/.hermes/data/` (or `./data/` if env var not set)
- Activates the pre-commit guardrail hook: `git config core.hooksPath scripts/hooks`
- Verifies Ollama connectivity

### 3. Manual Installation (if bootstrap is unavailable)

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[webapp,dev]"
mkdir -p data/queue data/traces
git config core.hooksPath scripts/hooks
```

---

## First-Time Setup

### Create the Data Directory

```bash
# Default location (relative to project root)
mkdir -p data/queue data/traces

# Or set a custom external data dir
export HERMES_DATA_DIR=~/.hermes/data
mkdir -p ~/.hermes/data/queue ~/.hermes/data/traces
```

### Verify Ollama Is Reachable

```bash
curl http://localhost:11434/api/tags
# Should return JSON listing installed models
```

### Configure Environment (optional)

Copy the example env file and adjust:

```bash
cp .env.example .env  # if provided
```

Or set env vars directly:

```bash
export HERMES_OLLAMA_URL=http://localhost:11434   # default
export HERMES_MODEL=llama3.2:3b                  # default
export HERMES_CRITIC_MODEL=llama3.2:3b           # default (same model)
export HERMES_DATA_DIR=./data                    # default
```

---

## Starting the Web Server

```bash
# Default port 8000
bash scripts/start-web.sh

# Custom port
bash scripts/start-web.sh --port 8080

# Or directly with uvicorn
source .venv/bin/activate
uvicorn hermes_assistant.webapp.server:app --host 127.0.0.1 --port 8000 --reload
```

The dashboard is available at: `http://localhost:8000`  
The API docs are available at: `http://localhost:8000/docs`

---

## Starting the TUI (Terminal Interface)

```bash
source .venv/bin/activate
hermes tui
```

---

## Verify the Installation

Run the test suite to confirm everything works:

```bash
source .venv/bin/activate
pytest tests/ -q --tb=short \
  --ignore=tests/e2e/ \
  --ignore=tests/test_rag_integration.py
# Expected: 744+ pass, <10 fail (pre-existing), 9 skip
```

Run a quick smoke test against the running server:

```bash
# Health check
curl http://localhost:8000/health

# Chat endpoint
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello", "session_id": "smoke-test"}'

# Import endpoint
curl -X POST http://localhost:8000/api/import/json \
  -H "Content-Type: application/json" \
  -d '{"risks": [], "tasks": [], "plans": []}'
```

---

## Monitoring

### Logs

Application logs are written to:
- `data/traces/llm_trace.jsonl` — LLM request/response traces (JSONL format)
- Standard output when running with `--reload` (development)
- Configure a log file with uvicorn: `uvicorn ... --log-config log_config.yaml`

### Job Queue

Review queued and completed critic jobs:

```bash
hermes jobs list
hermes jobs status <job-id>
```

---

## Troubleshooting

### Ollama Not Found

```
ConnectionRefusedError: [Errno 61] Connection refused
```

Solution:
```bash
ollama serve &   # Start Ollama in background
# or
brew services start ollama  # macOS with Homebrew
```

### Data Directory Permissions

```
PermissionError: [Errno 13] Permission denied: './data/risks.db'
```

Solution:
```bash
chmod 755 data/
chmod 644 data/*.db 2>/dev/null || true
```

### Port Already in Use

```
ERROR: [Errno 48] Address already in use
```

Solution:
```bash
# Find what is using the port
lsof -i :8000
# Kill it or use a different port
bash scripts/start-web.sh --port 8080
```

### Missing Optional Dependencies

```
ModuleNotFoundError: No module named 'docx'
```

Solution:
```bash
pip install -e ".[webapp,dev]"
# For full RAG support:
pip install python-docx pypdf openpyxl
```

### Pre-commit Hook Blocks a Commit

```
HERMES-Guardrail: runtime/confidential file blocked: *.db
```

Solution:
```bash
# Remove the blocked file from staging
git restore --staged <file>
# Ensure data/ files are in .gitignore
echo "data/*.db" >> .gitignore
git add .gitignore
git commit -m "fix: exclude runtime db files"
```

---

## Upgrading

```bash
git pull origin main
source .venv/bin/activate
pip install -e ".[webapp,dev]" --upgrade
# Run migrations if any (currently none)
pytest tests/ -q --tb=short --ignore=tests/e2e/
```

---

## Production Hardening (Staging → Production)

Before promoting to production, additionally:

1. Set `DEBUG=false` in environment
2. Put nginx or caddy in front of uvicorn (TLS termination)
3. Bind uvicorn to `127.0.0.1` only (never `0.0.0.0` unless behind a reverse proxy)
4. Set `HERMES_DATA_DIR` to a path on a backed-up volume
5. Enable log rotation for `data/traces/llm_trace.jsonl`
6. Run `pytest tests/e2e/` with Playwright installed to validate UI flows
7. Configure Ollama with `OLLAMA_HOST=127.0.0.1` (already default)
