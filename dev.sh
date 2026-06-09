#!/bin/bash
# RxWatcher dev startup — runs FastAPI + Next.js simultaneously
# Usage: ./dev.sh

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "🦷  RxWatcher dev environment starting…"
echo ""

# Check Python venv
if [ ! -d "$ROOT/.venv" ]; then
  echo "Creating Python venv…"
  python3 -m venv "$ROOT/.venv"
fi

source "$ROOT/.venv/bin/activate"

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

# Clean up both on Ctrl-C
trap "echo ''; echo 'Shutting down…'; kill $FASTAPI_PID $NEXT_PID 2>/dev/null; exit" INT TERM
wait