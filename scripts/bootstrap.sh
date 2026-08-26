#!/usr/bin/env bash
set -euo pipefail

echo "🚀 Bootstrapping HERMES Local Assistant..."

# 1) Python environment
echo "📦 Creating Python virtual environment..."
python -m venv .venv
source .venv/bin/activate
pip install -U pip setuptools wheel

echo "📚 Installing dependencies..."
pip install -e ".[dev]"

# 2) Pull Ollama models
echo "🧠 Pulling Ollama models (this may take a few minutes)..."
echo "   - qwen3:4b (router)"
ollama pull qwen3:4b || echo "⚠️  Failed to pull qwen3:4b (Ollama may not be running)"

echo "   - qwen3-30b-a3b-instruct-2507:q4_K_M (planner)"
ollama pull qwen3-30b-a3b-instruct-2507:q4_K_M 2>/dev/null || \
ollama pull qwen3-30b-a3b-instruct-2507 || \
  echo "⚠️  Qwen3-30B-A3B not available; will use fallback"

echo "   - bge-m3 (embeddings)"
ollama pull bge-m3 || echo "⚠️  Failed to pull bge-m3 (Ollama may not be running)"

# 3) Wire the guardrail pre-commit hook
# core.hooksPath is per-clone local config, so it cannot be committed — without
# this step every fresh clone runs unprotected (and security_audit's hook check
# has nothing to verify).
echo "🪝 Wiring the pre-commit guardrail hook..."
chmod +x scripts/hooks/pre-commit 2>/dev/null || true
git config core.hooksPath scripts/hooks

# 4) Initialize directories
echo "📁 Creating data directories..."
mkdir -p data/{corpus,projects,vectorstore}

echo ""
echo "✅ Bootstrap complete!"
echo ""
echo "📝 Next steps:"
echo "   1. Ensure Ollama is running: ollama serve"
echo "   2. Run tests: pytest -q"
echo "   3. Run CLI: python -m hermes_assistant.cli --help"
echo ""
echo "🧪 To validate token generation speed:"
echo "   bash scripts/bench.sh"
