# SceneTrace

SceneTrace helps you investigate what happened in a video. Upload a recording, mark areas of interest, and review detected events alongside the frames and clips that support them.

It runs a pretrained object detector on sampled video frames, tracks objects over time, and applies rules to flag possible events. A reviewer inspects the evidence, adds a note and exports a report. It is a local research prototype for human review: a finding is a candidate, not a conclusion about intent or safety.

## What you can do

- Upload a short video and draw restricted or passage zones.
- Run local analysis and review a timeline of candidate events.
- Inspect source frames and clips, filter or search events, and save review decisions.
- Explore the evaluation results and the system design inside the application.
- Export an investigation report as HTML, Markdown or JSON.

The rules flag three things: a person or object entering a restricted zone, a stationary object, and possible passage occupancy. Image overlap does not prove a physical obstruction, and a stationary object is not automatically unattended.

## How well does it work?

Short answer: it runs reliably, and on the small amount of footage tested it raised few false alerts, but the evidence is thin. Read the sample sizes.

| What was measured | Result | Sample |
|---|---|---|
| Does the pipeline run on varied video? | All 19 clips processed with no failure: four codecs (VP8, VP9, AV1, Theora), 15 to 60 fps, 640x360 up to 4K. Frame counts matched the expected number within 2. 4K AV1 decodes at about real time; the rest run 2 to 3 times faster than real time on a laptop CPU. | 19 clips |
| Do overlays line up on rotated phone video? | Yes at 90, 180 and 270 degrees; now a regression test. | 3 rotations |
| Event matching against annotations | Matched 3 of 4 annotated events (one missed by strict 0.5 temporal IoU). | 4 events, 5 recordings |
| Are the "false positives" real errors? | No. Reviewing each predicted event's own evidence showed the flagged objects were real: a second stationary car in a traffic jam that nobody annotated, and a person whose interval started 1.4 s late. | 4 events audited |
| False alerts where nothing should fire (third batch) | 0 on 3 negative zones in 3 new recordings (137.7 s in total), including a busy indoor corridor and a glass platform. Earlier batches are in the expansion document. | 3 negative zones |
| Audited precision on a busy held-out entrance (never seen during development) | 19 of 19 decided events showed a real person inside the zone; 5 more were ambiguous (small or overlapped people, possible identity switches). Recall is not measured there. | 24 events |

What this does **not** show: recall on new scenes, performance outside these clips, tracker identity quality (no ground-truth tracks exist), or anything about warehouses. All real-footage sets are tiny, annotated by one reviewer, and every held-out set was run once and then retired. A run with no findings does not certify a video is incident-free: the aerial roundabout test clip produced zero alerts because the detector found no vehicles at all (the run is flagged `sparse_detections`).

A known limit worth stating: the detector rescales every frame to roughly 320 to 640 px internally, so distant, small objects are often missed. Raising that size finds many more small objects (Washington DC clip: 20 detections at the default, 109 at 640) but costs about twice the runtime, and the data was too small to choose a size without tuning to the score, so the default is unchanged.

Full numbers, methods and failure cases: [docs/EVALUATION-RELIABILITY.md](docs/EVALUATION-RELIABILITY.md), [docs/EVALUATION-EXPANSION.md](docs/EVALUATION-EXPANSION.md), the Evaluation page, [data card](docs/DATA-CARD.md) and [model card](docs/MODEL-CARD.md).

## Experimental features

These exist, are tested for plumbing, and are **not validated**. They are optional and clearly labelled in the product.

- **Semantic search** (works reasonably on a small test). Describe what you want ("red car"). A CLIP model ranks events by how well their saved frames and crops match; structured filters apply first. The score is a ranking aid, never a confidence. On 11 labelled queries over 21 events the right event ranked first for 8 and in the top three for 10; ordering by time found it first for 2.
- **Descriptions** (weak). A small vision-language model can describe an event's saved frame. In our check only 3 of 21 descriptions were mostly supported by the frame and 17 invented some detail. The panel is collapsed and labelled experimental, shows its evidence and automatic checks, and never changes an event, a review or a report.
- **Cross-camera association** (off by default). Linking tracks between two cameras with generic image embeddings proved unreliable: at a moderate similarity threshold most different people in the same scene would be linked. The endpoint exists only if you set `VI_EXPERIMENTAL_CROSSCAM=on`, its default threshold is strict, and true accuracy is not measured because no multi-camera identity labels exist. There is no UI for it.
- **Fine-tuning** (opt-in). `python -m video_investigator.training.finetune` fine-tunes the detector on a CC0-declared worksite dataset. On a held-out 800-image test it detects helmets (AP50 0.69) and heads (0.50), which the pretrained model cannot, but did not improve person detection, the one shared class. See [docs/FINETUNING.md](docs/FINETUNING.md). The default detector is unchanged.

## Run locally

Tested on an Apple M4 Mac with CPU inference. You need Python 3.11, Node.js 20 or later, `uv`, and FFmpeg with H.264 support. The first model and media downloads need an internet connection.

```bash
uv venv --python 3.11 .venv
source .venv/bin/activate
uv pip install -r requirements.lock
uv pip install -e . --no-deps
python -m video_investigator.cli doctor
python scripts/fetch_demo_media.py
cd web && npm ci && cd ..
scripts/dev.sh
```

Open **http://127.0.0.1:5173**. Upload `var/candidates/pedestrian_area.webm`, draw and save a zone, select **Process video**, then select an event to inspect its evidence. Logs are in `var/dev/`. Stop everything with `scripts/dev.sh stop`.

Sample media and run data are not in the repository; see [third-party notices](THIRD-PARTY-NOTICES.md) for sources and licences.

## Read-only demo and deployment

`python -m video_investigator.cli export-demo` exports a finished run for a read-only demo (`http://127.0.0.1:5173/?mode=demo`); it runs no model. `scripts/build_demo.sh` builds a static site in `web/dist` and `python scripts/serve_static.py web/dist` previews it with production headers. A Docker image and compose file run the live backend. Both were built and checked locally; **nothing is deployed**. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for configuration, storage, resources and costs.

## How it works

```text
Video -> frames -> object detection -> tracking -> event rules
                                                      |
                                     evidence -> timeline -> human review
```

A FastAPI service manages uploads and runs; one worker processes video and saves evidence; SQLite stores runs, events and reviews; a React interface shows the recording, timeline and findings. A run is marked complete only after its artifacts are saved. The tracker is a custom baseline with no appearance model, so it can split or switch identities when people cross or are hidden; how often is not measured.

SceneTrace does not identify people, determine intent or blame, or make safety-compliance decisions. Live hosting beyond one machine, separate frontend and backend hosting, retention and backups are not built.

## Tests

```bash
python -m pytest                       # 116 offline tests (fixtures and test doubles, no downloads)
python -m pytest -m real_inference     # 6 tests with the real models and clips
(cd web && npm test && npm run build)  # 14 unit tests, type-check, build
```

Browser flows (real Brave through puppeteer-core, against the running stack): `node web/e2e/browser.mjs <clip>`, `semantic.mjs`, `explain.mjs`, `evaluation.mjs`, and `demo.mjs` (set `UI_URL` and `DEFAULT_DEMO=1` for the static build). Offline tests check code paths, not detector accuracy. Evaluation commands: `evaluate`, `evaluate-expansion`, `evaluate-reliability` (held-out sets run once; a second run is refused), and `scripts/robustness_sweep.py`.

## Project layout

- `src/video_investigator/api/`, `db/`, `worker/`: endpoints, persistence, background jobs.
- `media/`, `vision/`, `events/`, `reports/`: decoding, detection, tracking, event rules, evidence.
- `search/`, `explain/`, `crosscam/`: the experimental features above.
- `evaluation/`, `training/`: benchmarks, audits and opt-in fine-tuning.
- `web/`: React interface, static demo and browser checks.
- `fixtures/benchmark/`, `docs/evidence/`: manifests, freezes, audit labels and recorded results.
