#!/usr/bin/env bash
# DuckDuckGo search via a headed Chromium session (captcha-friendly).
# Starts Chromium with remote debugging on :9222 if not already running, then
# searches lite.duckduckgo.com. If DDG's Anomaly wall appears, solve it in the
# visible window — the script waits up to 5 minutes, then prints results.
#
# Usage: ./ddg-search.sh "<query>"
set -euo pipefail
cd "$(dirname "$0")"

BT=/home/dimchee/.pi/agent/skills/pi-skills/browser-tools

# Ensure Chromium is up on :9222 (headed, persistent profile in ~/.cache/browser-tools)
if ! curl -sf --max-time 2 http://localhost:9222/json/version >/dev/null; then
  echo "Starting Chromium on :9222 ..." >&2
  node "$BT/browser-start.js"
fi

node "$(dirname "$0")/ddg-search.mjs" "$@"
