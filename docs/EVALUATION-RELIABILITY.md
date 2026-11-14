# Reliability evaluation (third batch, audit and robustness)

This extends [EVALUATION-EXPANSION.md](EVALUATION-EXPANSION.md). Nothing in detection, tracking or the event rules changed: the config hash is still `cc3da6c063a4...` (see `fixtures/benchmark/FREEZE-3.json`). Results are descriptive; the samples are small and annotated by one reviewer.

## What was added

- **dev-3**: one fixed-camera indoor mall corridor (Ljubljana, CC BY 3.0), 61.8 s, one negative zone (a balcony nobody should enter).
- **test-3** (frozen before it was run, run once): an indoor entrance in low light (CC BY 3.0) with two units, and a glass-walled rail platform (CC BY-SA 4.0). Total 75.9 s, 2 negative zones and 1 audit unit.
- Sources, authors and licences are in `fixtures/benchmark/manifest_reliability.json` and the third-party notices. Candidate clips were screened for a fixed camera (median phase-correlation shift under 1 px); handheld and shaky clips were rejected.

## Audit units

The busy entrance has people continually entering the walkway, and positive events could not be annotated reliably. Instead of inventing ground truth, every event the system predicted was reviewed against its own saved evidence frames and labelled supported, unsupported or ambiguous (`fixtures/benchmark/audit_labels.json`).

Audited precision is supported / (supported + unsupported). Ambiguous events are excluded, not assumed correct. Recall is not measured.

## Results

| Set | Result |
|---|---|
| dev-3 negative (61.8 s) | 0 false alerts |
| test-3 negatives (2 zones) | 0 false alerts over 0.021 negative hours |
| test-3 entrance audit | 24 events: 19 supported, 0 unsupported, 5 ambiguous. Audited precision 19 of 19 |

The ambiguous events are mainly small, partly hidden people and tracks that may have switched identity part-way.

Earlier events re-audited from their evidence: the two apparent false positives in the earlier sets (a second stationary car in a traffic jam that the annotation did not cover, and a person whose annotated interval began 1.4 s after the system flagged them) were real objects. The frozen-test "false positive" was not a duplicate track fragment: the two tracks are different cars (box overlap 0.0 over 37 shared frames) and no duplicate pairs exist. An earlier note claiming fragmentation was wrong and has been corrected.

## Limits

- 19 of 19 is a small, single-reviewer, single-scene audit. It says nothing about recall or other scenes.
- A zone drawn too generously will raise events for people who are merely nearby; that depends on the zone, not only the model.
- Tracker identity quality is unmeasured (no ground-truth tracks).
- Negative-only recordings test that nothing fires, not that real events are caught.

## Detector input size (development data only)

The detector rescales frames to 320 to 640 px. On development clips a larger size finds more small objects at about 1.7 to 2.3 times the cost, but event outcomes were unstable and the data too small to pick a value without tuning to the score. The default is unchanged. These are counts, not accuracy.

## Robustness sweep

`scripts/robustness_sweep.py` ran the full pipeline over 19 clips: VP8, VP9, AV1 and Theora, 15 to 60 fps, 640x360 to 4K. All completed, frame counts were within 2 of expected, and 4K AV1 decodes at about real time (the rest are faster). Results: `docs/evidence/robustness-sweep.json`. A rotation regression test (90, 180, 270 degrees) checks overlays stay aligned on phone video.

## Experimental features

Cross-camera association is now off unless `VI_EXPERIMENTAL_CROSSCAM=on`. Descriptions stay available but collapsed and labelled unreliable (3 of 21 mostly supported). Semantic search stays, framed as a ranking aid.

## Reproduce

```bash
python -m video_investigator.cli evaluate-reliability          # development lane
python -m video_investigator.cli evaluate-reliability --include-test3   # refused if already run
python -m video_investigator.cli audit-refresh                 # recompute audit from labels only
python scripts/robustness_sweep.py
```

## Checks run for this batch (14 Nov 2026, Apple M4, CPU)

- Offline `pytest`: 116 passed. `pytest -m real_inference`: 6 passed. Frontend: `tsc`, 14 unit tests and the build passed.
- Real-browser flows (Brave via puppeteer-core, live stack with real models): upload, zone drawing, processing, review, export, semantic search, descriptions and evaluation page all passed. In the main flow, the check that the Evaluation page heading renders failed on a fresh data directory because the core development and frozen-test reports were not in it; copying them in made the evaluation flow pass. The exact main-flow check was not re-run afterwards.
- Not tested: the static demo and Docker image were not rebuilt for this batch, and nothing was deployed.
- Not added: dedicated Evaluation-page cards for the reliability batch and robustness sweep (results are in the evidence files and this document).
