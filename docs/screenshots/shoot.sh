#!/usr/bin/env bash
# Capture app screenshots with headless Chrome (server must be running on :8000, or set PORT=...).
# usage: ./shoot.sh name "query-string"   e.g. ./shoot.sh live "run=live_20260930_1900&view=15.2,87.2,6&hour=24"
set -u
cd "$(dirname "$0")"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
name=$1; query=$2
profile=${PROFILE:-$(mktemp -d)}   # set PROFILE=dir to reuse the tile cache across shots
rm -f "$name.png"
"$CHROME" --headless=new --disable-gpu --hide-scrollbars --window-size=1600,900 --force-device-scale-factor=1.5 \
  --virtual-time-budget=${BUDGET:-30000} --user-data-dir="$profile" \
  --screenshot="$PWD/$name.png" "http://localhost:${PORT:-8000}/?$query" >/dev/null 2>&1 &
pid=$!
for _ in $(seq 1 90); do [ -s "$name.png" ] && break; sleep 1; done
sleep 1
kill "$pid" 2>/dev/null; pkill -f "$profile" 2>/dev/null; [ -z "${PROFILE:-}" ] && rm -rf "$profile"
ls -la "$name.png"
