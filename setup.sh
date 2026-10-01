#!/usr/bin/env bash
# One-time setup on a new machine: Python environment + (optionally) rebuild the web app.
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
"$PY" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
"$PY" -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
if command -v npm >/dev/null 2>&1; then
  (cd frontend && npm install && npm run build)
else
  echo "npm not found: using the pre-built web app in frontend/dist"
fi
echo "Done. Start the demo with ./run_demo.sh and open http://localhost:8000"
