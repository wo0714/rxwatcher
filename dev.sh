#!/bin/bash
# RxWatcher dev startup — runs FastAPI + Next.js simultaneously
# Usage: ./dev.sh
#
# Copyright (c) 2026 Wayne Ohm / YC Lab. All rights reserved.

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "🦷  RxWatcher dev environment starting…"
echo ""

# ── Clean up any leftover processes from a previous run ──────────────────────
# Graceful SIGTERM first (lets Next.js/Turbopack flush its .next cache
# properly before exiting — a hard kill -9 mid-write is what corrupts the
# cache and causes "@swc/helpers ... Cannot find module" errors later).
for PORT in 3010 8000; do
  PIDS=$(lsof -ti:$PORT 2>/dev/null || true)
  if [ -n "$PIDS" ]; then
    echo "$PIDS" | xargs kill 2>/dev/null || true
  fi
done
sleep 1
for PORT in 3010 8000; do
  PIDS=$(lsof -ti:$PORT 2>/dev/null || true)
  if [ -n "$PIDS" ]; then
    echo "$PIDS" | xargs kill -9 2>/dev/null || true
  fi
done

# Check Python venv
if [ ! -d "$ROOT/.venv" ]; then
  echo "Creating Python venv…"
  python3 -m venv "$ROOT/.venv"
fi

source "$ROOT/.venv/bin/activate"

# Load environment variables
if [ -f "$ROOT/.env" ]; then
  set -a
  source "$ROOT/.env"
  set +a
fi

# Install Python deps if needed
pip install -q -r "$ROOT/requirements.txt"

# Ensure data dirs exist
mkdir -p "$ROOT/data/scans" "$ROOT/data/output"

# Start FastAPI in background
echo "▶  FastAPI  → http://localhost:8000"
uvicorn processor.api:app --reload --port 8000 &
FASTAPI_PID=$!

# Start Next.js
echo "▶  Next.js  → http://localhost:3010"
echo ""
cd "$ROOT/web" && npm run dev -- --port 3010 &
NEXT_PID=$!

# ── Graceful shutdown on Ctrl-C ───────────────────────────────────────────────
# SIGTERM first so Next.js/Turbopack can flush its cache cleanly; force-kill
# after a short grace period only if it hasn't exited on its own.
cleanup() {
  echo ''
  echo 'Shutting down…'
  kill "$FASTAPI_PID" "$NEXT_PID" 2>/dev/null || true
  sleep 2
  kill -9 "$FASTAPI_PID" "$NEXT_PID" 2>/dev/null || true
  exit
}
trap cleanup INT TERM

wait