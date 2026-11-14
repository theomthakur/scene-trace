# Implementation status

Last updated 14 November 2026. Local build only: nothing pushed, published or deployed. Hardware: Apple M4, 16 GB, CPU inference, Python 3.11.15, torch 2.15.0, torchvision 0.29.2, PyAV 18.1.0, OpenCV 5.0.0, Node 24.

## Gates
| Gate | Status | Evidence (actual outcomes) |
|---|---|---|
| G0 environment, detector, lawful clip | **Met** | `docs/evidence/g0-doctor-pedestrian_area.json`: real COCO weights (SHA-256 `907ea3f9...`) detected 7 people in the first frame in 65 ms on CPU. Two CC0 clips, SHA-1 verified, manifest in `fixtures/benchmark/manifest.json`, licences in `THIRD-PARTY-NOTICES.md`. |
| G1 package, contracts, DB, upload | **Met** | Clean install from `requirements.lock` in a fresh clone; migration runner (idempotent, WAL, foreign keys, busy timeout); upload, probe, derivative and Range playback tested (206, 416, tail ranges, original byte-identical). Corrupt, truncated, renamed non-video, empty, oversize (413 while streaming) and untimed inputs have explicit codes. |
| G2 decode, detect, track artifacts | **Met** | `cli process` on the real clip: 75 sampled frames, 651 detections, 5.6 s. Boxes verified visually on the original 1920x1080 frame; timestamps, variable pts and rotation unit-tested; output byte-identical across reruns on this machine; `verify_attempt` reports no problems. |
| G3 temporal events and evidence | **Met (rules); partly (real data)** | 12 fixture scenarios match truth exactly (11 events, 0 false); threshold equality, gaps, hysteresis, jitter, tentative tracks and no-merge-across-tracks covered. Real events produce overlay frames, originals and padded H.264 clips; evidence frame times equal stored observation times and sizes equal the video. |
| G4 durable jobs and API | **Met** | Real SIGKILL of a worker mid-run: run becomes `interrupted`, no manifest, original intact, restart creates attempt 2 and completes with no duplicated events. Cancel (running and queued), duplicate `client_request_id`, one active job, stale lease recovery, disk-full (no retry), one automatic retry for a transient storage error, missing weights (fails loudly, never falls back), manifest-before-completion are all tested. |
| G5 usable investigation UI | **Met** | `web/e2e/browser.mjs` in real Brave via puppeteer-core against the live stack: 27 of 27 checks pass (upload, pointer-drawn zone, undo, save, process with the real detector, events, evidence images, overlay toggle, thumbnail seek, review, timeline keyboard, reload persistence, search, unsupported query, export, 390 px width, no console errors). `web/e2e/demo.mjs`: 10 of 10 (static demo distinct and read-only, no backend calls, backend-offline state). Running it found and fixed five real UI bugs. |
| G6 search and evaluation | **Met, with weak data** | Search maps queries to known events and refuses unsupported intents. Frozen test split run once (`docs/evidence/test-results.json`; a second run is refused and unit-tested). Report: `docs/evidence/evaluation-frozen-test.json`. |
| G7 delivery and docs | **Met** | Fresh clone: install from lock, 64 offline tests, doctor, fixture report reproduced byte for byte, clips fetched and verified, 4 real-inference tests, `npm ci`, 14 frontend tests, production build. README, notices, ledger, data and model cards, walkthrough written. |

## Measured results (read the denominators)
- **Fixtures (no detector):** 11/11 truth events matched, 0 false positives. The no-persistence baseline gives 12 false positives on the same fixtures. Says nothing about real video.
- **Real development footage (pedestrian clip):** 1 matched, 1 false positive, 1 missed of 2 annotated doorway events; mean onset error 200 ms (one match). The unmatched pair had temporal IoU 0.47, just under the 0.5 rule. Negative zone: 0 false alerts. No-persistence baseline: 1 matched, 5 false positives.
- **Frozen test (traffic clip, run once, not blind):** the red stationary car matched (temporal IoU 0.52, just above the threshold), plus 1 false positive that is a second track fragment of the same car. People-only negative strip: 0 false alerts. No-persistence baseline: 177 false positives. Precision 0.5, recall 1.0 on 1 annotated event. Not evidence of generalisation.
- **Speed:** about 73 ms per sampled frame; 75 frames in about 5.6 s (2.6x real time) on CPU.
- **Not measured:** detection mAP, tracking metrics, passage events on real footage, retrieval Recall@k, explanation quality (none exists), human review time.

## Unmet or weak, stated plainly
- **Benchmark size:** 2 independent recordings, not 12. One annotator, and the annotator had already seen detector output on both clips. Both clips are outdoor and low-angle, not an indoor aisle.
- **Tracker quality:** identities fragment in crowds (about 117 tracks for roughly 9 people per frame). It is a baseline, not ByteTrack.
- **Weights licence:** the licence of the pretrained weights file is unresolved (see notices). Not redistributed.
- **Browser coverage:** Chromium-based Brave only; no Firefox or Safari, no screen reader, no touch hardware, no forced-colours check. Narrow width tested at 390 px only.
- **Platforms:** Linux, Windows, MPS and CUDA were not tested. The lock file is from macOS arm64 and is not hash-pinned. Real-inference determinism was observed on one machine only.
- **Duplicate FFmpeg libraries:** PyAV and OpenCV both bundle FFmpeg, producing a harmless-looking macOS warning; unverified elsewhere.
- **Not built:** embeddings or video-language explanation, cross-camera tracking, fine-tuning, cloud deployment, authentication (single-user loopback only).
- **Housekeeping:** an empty folder `~/tmp-e2e` was created by mistake and the safety check blocked my removal; delete it yourself.
