#!/usr/bin/env bash
# Benchmark token generation speed on actual hardware.

set -euo pipefail

OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"

echo "🚀 Benchmarking HERMES model roster..."
echo "Target: i7-1265U + 64 GB RAM (bandwidth-bound, not CPU-bound)"
echo ""

# Function to bench a model
bench_model() {
    local model=$1
    local role=$2

    echo "📊 Benchmarking: $model ($role)"

    # Simple curl to Ollama /api/generate
    # Time the response and estimate tok/s
    response=$(curl -s -X POST "$OLLAMA_HOST/api/generate" \
        -H "Content-Type: application/json" \
        -d "{
            \"model\": \"$model\",
            \"prompt\": \"Write a short 100-word technical summary.\",
            \"stream\": false,
            \"options\": {\"num_thread\": 10}
        }")

    # Extract eval_count and eval_duration
    eval_count=$(echo "$response" | grep -o '"eval_count":[0-9]*' | cut -d: -f2)
    eval_duration=$(echo "$response" | grep -o '"eval_duration":[0-9]*' | cut -d: -f2)

    if [[ -n "$eval_count" && -n "$eval_duration" ]]; then
        # eval_duration is in nanoseconds
        eval_duration_sec=$(echo "scale=3; $eval_duration / 1000000000" | bc)
        tok_per_sec=$(echo "scale=2; $eval_count / $eval_duration_sec" | bc)
        echo "   ✓ Generated $eval_count tokens in ${eval_duration_sec}s = $tok_per_sec tok/s"
    else
        echo "   ✗ Could not parse response (Ollama may not be running)"
    fi
    echo ""
}

# Benchmark key models
bench_model "qwen3:4b" "ROUTER"
bench_model "qwen3-30b-a3b-instruct-2507:q4_K_M" "PLANNER" 2>/dev/null || \
bench_model "qwen3-30b-a3b-instruct-2507" "PLANNER" 2>/dev/null || \
  echo "⚠️  Qwen3-30B-A3B not available"
bench_model "bge-m3" "EMBED"

echo "✅ Benchmark complete. Compare against target estimates in CLAUDE.md."
