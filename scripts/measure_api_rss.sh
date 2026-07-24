#!/usr/bin/env bash
# Reproduces LOG entry 27's API resident-footprint measurement:
# RSS at startup, after the first /api/health (which unpickles the bundle
# in current code), and after mixed traffic — then the same with the
# bundle file absent, isolating the unpickle path's cost.
# Run from the repo root with the venv active:  bash scripts/measure_api_rss.sh
set -euo pipefail
PORT="${PORT:-8123}"
run_case () {
  python -m uvicorn vpredict.serving.api:create_app --factory --port "$PORT" \
    >/tmp/api-rss.log 2>&1 &
  PID=$!; sleep 6
  R0=$(ps -o rss= -p "$PID")
  curl -s "localhost:$PORT/api/health" >/dev/null; sleep 1
  R1=$(ps -o rss= -p "$PID")
  for _ in 1 2 3; do
    curl -s "localhost:$PORT/api/health" >/dev/null
    curl -s "localhost:$PORT/api/scoreboard" >/dev/null
    curl -s "localhost:$PORT/api/upcoming" >/dev/null
  done; sleep 1
  R2=$(ps -o rss= -p "$PID")
  kill "$PID" 2>/dev/null; wait "$PID" 2>/dev/null || true
  echo "$1: startup=$((R0/1024))MB after-first-health=$((R1/1024))MB after-traffic=$((R2/1024))MB"
}
run_case "WITH bundle (current behavior)"
if [ -f data/models/model.joblib ]; then
  mv data/models/model.joblib /tmp/model.joblib.rss-bak
  run_case "WITHOUT bundle (no unpickle path)"
  mv /tmp/model.joblib.rss-bak data/models/model.joblib
fi
