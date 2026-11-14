#!/usr/bin/env bash
# Build the read-only static demo into web/dist (no backend, no model). Needs a completed local run to export.
#   scripts/build_demo.sh            export the latest completed run, then build in demo mode
#   scripts/build_demo.sh --reuse    reuse the existing web/public/demo bundle
# The result is a plain static folder: deploy it with `vercel deploy web/dist` (only when you decide to; this script never deploys).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
source .venv/bin/activate
if [ "${1:-}" != "--reuse" ]; then python -m video_investigator.cli export-demo --out web/public/demo; fi
[ -f web/public/demo/index.json ] || { echo "No demo bundle: process a video locally first, then rerun."; exit 1; }
(cd web && npm run build:demo)
cp deploy/vercel/vercel.json web/dist/vercel.json
du -sh web/dist | sed 's/^/built web\/dist: /'
echo "Local preview with the production headers: python scripts/serve_static.py web/dist"
