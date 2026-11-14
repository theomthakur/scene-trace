#!/usr/bin/env bash
# Start (or stop) the local stack: API on 8000, one worker, Vite dev server on 5173. Loopback only.
#   scripts/dev.sh          start everything in the background
#   scripts/dev.sh stop     stop everything this script started
# Logs and PIDs live in var/dev/. Set VI_DATA_DIR to use a different data directory.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
RUN="$ROOT/var/dev"; mkdir -p "$RUN"
stop() {
  pkill -f "$ROOT/web/node_modules/.bin/vite" 2>/dev/null || true      # also catches Vite servers from earlier starts whose PID files were overwritten
  for f in "$RUN"/*.pid; do
    [ -e "$f" ] || continue
    pid="$(cat "$f")"
    if kill -0 "$pid" 2>/dev/null; then kill "$pid" 2>/dev/null || true; for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$pid" 2>/dev/null || break; sleep 0.3; done; kill -9 "$pid" 2>/dev/null || true; fi
    rm -f "$f"
  done
  echo "stopped"
}
if [ "${1:-}" = "stop" ]; then stop; exit 0; fi
[ -d .venv ] || { echo "No .venv. Create it: uv venv --python 3.11 .venv && uv pip install -r requirements.lock && uv pip install -e . --no-deps"; exit 1; }
source .venv/bin/activate
stop >/dev/null 2>&1 || true
nohup uvicorn video_investigator.api.app:app --host 127.0.0.1 --port 8000 > "$RUN/api.log" 2>&1 & echo $! > "$RUN/api.pid"
nohup python -m video_investigator.worker.main > "$RUN/worker.log" 2>&1 & echo $! > "$RUN/worker.pid"
if [ -d web/node_modules ]; then (cd web && nohup npm run dev > "$RUN/web.log" 2>&1 & echo $! > "$RUN/web.pid"); else echo "web/node_modules missing: run 'cd web && npm install' for the UI"; fi
for _ in $(seq 1 40); do curl -sf http://127.0.0.1:8000/api/health >/dev/null && break; sleep 0.5; done
curl -sf http://127.0.0.1:8000/api/health >/dev/null && echo "API up: http://127.0.0.1:8000  UI: http://127.0.0.1:5173" || { echo "API did not start; see $RUN/api.log"; exit 1; }
echo "Stop with: scripts/dev.sh stop"
