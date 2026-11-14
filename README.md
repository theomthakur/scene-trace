# SceneTrace

SceneTrace helps you investigate what happened in a video. Upload a recording, mark areas of interest, and review detected events alongside the frames and clips that support them.

The application runs a pretrained object detector on sampled video frames, tracks objects over time, and applies rules to flag possible events. A reviewer can inspect the supporting evidence, add a note and export a report. SceneTrace is a local research prototype for human review; a finding is not a conclusion about intent or safety.

## What you can do

- Upload a short video and draw restricted or passage zones.
- Run local analysis and review a timeline of candidate events.
- Inspect source frames and clips, filter or search events, and save review decisions.
- Explore evaluation results and the system design within the application.
- Export an investigation report as HTML, Markdown or JSON.

## Optional capabilities

Each is optional: if its model is missing or switched off, the rest of the application is unaffected.

- **Semantic search.** Describe what you are looking for ("red car", "person carrying a shopping bag"). A CLIP model ranks events by how well their saved frames and crops match. Structured filters (type, class, zone, time) apply first. The score is a ranking aid, not a confidence, and every result names the frame, crop and timestamp it came from. On 11 labelled queries over 21 events from two clips, the right event was ranked first for 8 and in the top three for 10; ordering by time found it first for 2.
- **Descriptions.** A small open vision-language model (SmolVLM-500M) can describe an event's saved frame. Each description shows the evidence it used and automatic checks, and is labelled unverified. It never changes an event, a review or a report. Measured honestly: of 21 descriptions, 3 were mostly supported by the frame, 12 mixed real and invented details, and 6 were mostly unsupported. Licence plates the model reads aloud are redacted.
- **Cross-camera association.** `POST /api/crosscam/associate` proposes candidate links between tracks from two runs, using timing and appearance. It is a hint for a reviewer, never an identification. Generic image embeddings turned out to be a weak basis: at a moderate threshold they linked most different people in the same scene, so the default threshold is strict and proposes very little. True cross-camera accuracy is **not measured** because no multi-camera identity labels are available.
- **Fine-tuning.** `python -m video_investigator.training.finetune` fine-tunes the detector heads on a CC0-declared worksite dataset (helmet, head, person) and compares the result with the pretrained baseline on a held-out test. The default detector is unchanged; a fine-tuned checkpoint is opt-in through `VI_DETECTOR_CHECKPOINT`. On a held-out 800-image test it reached helmet AP50 0.69 and head 0.50 (classes the pretrained model cannot detect at all) but did not improve the one shared class, person, where both models score near zero. One seed, CPU, five to fourteen minutes per run. Details: [docs/FINETUNING.md](docs/FINETUNING.md).

## Run locally

The recorded setup was tested on an Apple M4 Mac using CPU inference. You need Python 3.11, Node.js 20 or later, `uv`, and FFmpeg with H.264 encoding support. The first model and sample-media downloads require an internet connection. These commands run locally and start an API, one worker and the web interface.

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

Open **http://127.0.0.1:5173**. Upload `var/candidates/pedestrian_area.webm`, draw and save a zone, then select **Process video**. When the run finishes, select an event to inspect its evidence.

The API, worker and frontend logs are saved in `var/dev/`. Stop the local servers started by the script with:

```bash
scripts/dev.sh stop
```

The sample media and local run data are not included in the repository. The media-fetch script downloads two clips; see [third-party notices](THIRD-PARTY-NOTICES.md) for sources and license information.

## Read-only demo

After completing a local run, export its results for a read-only demo:

```bash
python -m video_investigator.cli export-demo
```

With the local frontend running, open `http://127.0.0.1:5173/?mode=demo`. The demo shows saved results and does not run any model. The bundle is local and ignored by Git; upload, processing and other live actions require the backend.

To build a deployable static site, run `scripts/build_demo.sh` (output in `web/dist`, with production security headers) and preview it with `python scripts/serve_static.py web/dist`. A Docker image and compose file run the live backend. Both were previously built and checked locally; **the repository does not establish a deployed instance**. Configuration, storage, resource needs and costs are in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## How it works

```text
Video → frames → object detection → tracking → event rules
                                               ↓
                              evidence → timeline → human review
```

A FastAPI service manages uploads and runs. One local worker processes video and saves evidence; SQLite stores runs, events and reviews. The React interface displays the recording, timeline and findings. A run is marked complete only after its artifacts are saved.

The current rules flag restricted-zone entry, stationary objects and possible passage occupancy. These are **candidates for review**: image overlap does not prove a physical obstruction, and a stationary object is not automatically unattended.

## Results and limitations

The default detector is a pretrained COCO model and the tracker is a custom baseline. The fine-tuning workflow produced a separate, opt-in checkpoint; it is not used unless you ask for it. The tracker can lose or split identities, especially in crowded scenes, and the detector can miss or misclassify objects.

The evaluation includes synthetic fixtures and real recordings: two in the original benchmark, plus three additional recordings in a separate expansion (two development clips and one frozen test clip). The expansion has one annotated positive event; its test clip is negative-only and the detector found no objects in it, so zero alerts there do not demonstrate reliable detection. These real-footage sets are small and not blind; their results do not establish performance in new environments. See [the expansion results](docs/EVALUATION-EXPANSION.md). See the Evaluation page, [data card](docs/DATA-CARD.md) and [model card](docs/MODEL-CARD.md) for scope and known gaps. A run with no findings does not certify that a video is incident-free.

SceneTrace does not identify people, determine intent or blame, or make safety-compliance decisions. Cross-camera linking and descriptions are hints for a human, with measured weaknesses described above. Live hosting beyond one machine, separate frontend and backend hosting, retention policies and backups are not built.

## Tests

```bash
python -m pytest                                   # offline suite (fixtures and test doubles; no model downloads)
(cd web && npm test && npm run build)
```
Browser flows (real Brave via puppeteer-core, against the running stack): `node web/e2e/browser.mjs <clip>`, `semantic.mjs`, `explain.mjs`, `evaluation.mjs`, and `demo.mjs` (set `UI_URL` and `DEFAULT_DEMO=1` for the static build).

The offline tests verify code paths with fixtures and test doubles; they are not a measurement of detector accuracy. Real-inference tests require the model weights and downloaded clips: `python -m pytest -m real_inference`. They are separate from the offline suite. See [the walkthrough](docs/WALKTHROUGH.md), [parameter ledger](docs/PARAMETER-LEDGER.md), [data card](docs/DATA-CARD.md) and [model card](docs/MODEL-CARD.md) for implementation details.

## Project layout

- `src/video_investigator/api/` and `db/`: API endpoints, persistence and review records.
- `src/video_investigator/worker/`, `media/`, `vision/` and `events/`: background jobs, video decoding, detection, tracking and event rules.
- `src/video_investigator/search/`, `explain/` and `crosscam/`: optional search, descriptions and association.
- `src/video_investigator/evaluation/`, `training/` and `reports/`: evaluation, opt-in fine-tuning and evidence exports.
- `web/`: React interface, static demo and browser checks.
- `fixtures/` and `docs/evidence/`: evaluation manifests and recorded results.

See [deployment readiness](docs/DEPLOYMENT.md) for the single-origin live service, Docker setup and the separate static-demo workflow.
