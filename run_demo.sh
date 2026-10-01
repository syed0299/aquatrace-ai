#!/usr/bin/env bash
# Build the web app (if needed) and start AquaTrace AI on http://localhost:8000
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d frontend/dist ]; then
  (cd frontend && npm install && npm run build)
fi
cd backend
exec ../.venv/bin/uvicorn aquatrace.api:app --host 127.0.0.1 --port 8000
