#!/usr/bin/env bash
# Start the HERMES Local Assistant web dashboard (Phase 4).
# Usage: bash scripts/start-web.sh [--port PORT]
set -euo pipefail

PORT="${1:-8000}"

# ── Resolve project root ───────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# ── Activate virtual environment ───────────────────────────────────────────
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    echo "ERROR: No virtual environment found."
    echo "       Run first: bash scripts/bootstrap.sh"
    exit 1
fi

# ── Check Ollama (optional, data refresh needs it) ─────────────────────────
if curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "Ollama: running"
else
    echo "WARNING: Ollama not running. Schedule/review data may be empty."
    echo "         Start with: ollama serve"
fi

# ── Install webapp dependencies if not present ─────────────────────────────
if ! python -c "import fastapi" 2>/dev/null; then
    echo "Installing webapp dependencies..."
    pip install -e ".[webapp]" -q
fi

# ── Create data directories if missing ────────────────────────────────────
mkdir -p data/projects data/queue data/traces

# ── Launch FastAPI server ──────────────────────────────────────────────────
echo ""
echo "HERMES Dashboard is starting..."
echo ""
echo "  URL: http://localhost:${PORT}"
echo ""
echo "  Screens:   1 Projects  2 Detail  3 Pendenzen  4 Reviews"
echo "  Shortcuts: d=theme  r=refresh  ?=help"
echo ""
echo "Press Ctrl+C to stop."
echo ""

exec uvicorn hermes_assistant.webapp.server:app \
    --host 127.0.0.1 \
    --port "$PORT" \
    --reload \
    --log-level warning
