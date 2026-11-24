#!/usr/bin/env bash
# Build the read-only static demo into web/dist-demo (no backend, no model). Needs a completed local run to export.
#   scripts/build_demo.sh            export the latest completed run, then build in demo mode
#   scripts/build_demo.sh --reuse    reuse the existing web/public/demo bundle
# The result is a plain static folder. This script never deploys.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
source .venv/bin/activate
if [ "${1:-}" = "--reuse" ]; then
  [ -f web/public/demo/index.json ] || { echo "No bundle at web/public/demo/index.json."; exit 1; }
  (cd web && npm run build:demo -- --outDir dist-demo)
else
  DEMO_PUBLIC="$(mktemp -d)"
  trap 'rm -rf "$DEMO_PUBLIC"' EXIT
  python -m video_investigator.cli export-demo --out "$DEMO_PUBLIC/demo" "$@"
  (cd web && npm run build:demo -- --mode static-demo --outDir dist-demo)
  cp web/public/favicon.svg web/dist-demo/
  cp -R "$DEMO_PUBLIC/demo" web/dist-demo/
fi
cp deploy/vercel/vercel.json web/dist-demo/vercel.json
du -sh web/dist-demo
echo "Local preview with the production headers: python scripts/serve_static.py web/dist-demo"
