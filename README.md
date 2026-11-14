# Video Investigation Platform

A local tool for answering "what happened in this video, where, and which evidence supports it". It runs a real pretrained object detector on decoded video pixels, tracks objects, turns noisy detections into rule-based event candidates over configurable zones, and gives a reviewer a timeline, evidence frames and clips, and a persisted review workflow.

It supports investigation. It does not infer intent, blame, identity or safety compliance, and it does not recognise faces or licence plates.

**Status:** local prototype, built and tested on one Apple M4 laptop (CPU inference). Nothing is deployed or published. See [IMPLEMENTATION-STATUS.md](IMPLEMENTATION-STATUS.md) for what is demonstrated and what is not.

## What is real and what is not
- **Real:** `fasterrcnn_mobilenet_v3_large_320_fpn` with COCO weights runs on actual decoded frames. The pipeline records the weights hash, timings and device.
- **Baseline, not state of the art:** the tracker is a custom IoU plus Hungarian baseline (not ByteTrack or DeepSORT). It fragments identities in crowded scenes. Nothing here is trained or fine-tuned.
- **Small evaluation:** two CC0 clips (goal was twelve) and generated fixtures. Real-footage figures rest on one to three events. Read the denominators.

## Quick start (macOS or Linux, Python 3.11, Node 20+, ffmpeg with libx264)
```bash
uv venv --python 3.11 .venv && source .venv/bin/activate
uv pip install -r requirements.lock && uv pip install -e . --no-deps
python -m video_investigator.cli doctor            # environment check, downloads the weights (78 MB) on first use
python scripts/fetch_demo_media.py                 # two CC0 clips, SHA-1 verified, into var/candidates/
(cd web && npm ci)
scripts/dev.sh                                     # API :8000, one worker, UI :5173  (scripts/dev.sh stop to stop)
```
Open http://127.0.0.1:5173, upload `var/candidates/pedestrian_area.webm`, draw a zone on the video, **Save zones**, **Process video** (about 6 s on CPU for that clip), click an event.

The commands from the brief work individually:
```bash
python -m video_investigator.cli doctor --clip var/candidates/pedestrian_area.webm
uvicorn video_investigator.api.app:app --port 8000
python -m video_investigator.worker.main            # add --once to drain the queue and exit
(cd web && npm run dev)
python -m video_investigator.cli process var/candidates/pedestrian_area.webm --zones fixtures/zones/pedestrian_area.json
python -m video_investigator.cli evaluate           # fixtures + development footage (the test split runs once, with --include-test)
python -m video_investigator.cli export-demo        # static, read-only demo bundle into web/public/demo
```
Static demo mode (no backend, visibly labelled): `http://127.0.0.1:5173/?mode=demo` after `export-demo`.

## Tests
```bash
python -m pytest                          # 64 offline tests (rules on fixtures, tracker, media, API, worker kill/restart, benchmark)
python -m pytest -m real_inference        # 4 tests with the real detector on the real clip (needs weights and clips)
(cd web && npm test && npm run build)     # 14 unit tests, type-check, production build
(cd web && node e2e/browser.mjs /tmp/clip.webm)   # real-browser flow; needs the stack running and a Chromium-based browser
```
Copy the clip outside `~/Documents` for the browser test on macOS: headless Brave was denied reading files there.

## How it works
`video -> probe and hash -> timestamped decode (PyAV, milliseconds) -> detector -> tracker -> versioned temporal rules over zones -> events with evidence -> review UI`. A single worker claims one run at a time from a SQLite job table with a lease and heartbeat. Artifacts are written first, a manifest is published atomically, and only then does the database say "completed". See `web` System Design view and [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md).

Events: restricted-zone entry (bottom-centre of the box inside a polygon for a dwell), stationary object candidate, and aisle occupancy candidate (2D overlap, not clearance). Parameters and their evidence are in [docs/PARAMETER-LEDGER.md](docs/PARAMETER-LEDGER.md).

## Honest limits
- A general COCO detector misses and mislabels objects; confidence is a model score, not a probability.
- Tracks are temporary within one run and fragment in crowds.
- A run with no events is not an incident-free certificate; quality flags travel with each run.
- Measured on one machine only; real inference was deterministic there. Other hardware may differ slightly.
- The demonstration clips are outdoor and low-angle, not an indoor aisle.
- Not built: embeddings, video-language explanation, cross-camera tracking, fine-tuning, cloud deployment.

Licences and notices: [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md). Data and model details: [docs/DATA-CARD.md](docs/DATA-CARD.md), [docs/MODEL-CARD.md](docs/MODEL-CARD.md).
