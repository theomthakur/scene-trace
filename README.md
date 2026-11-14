# SceneTrace

SceneTrace helps you investigate what happened in a video. Upload a recording, mark areas of interest, and review detected events alongside the frames and clips that support them.

The application runs a pretrained object detector on video frames, tracks objects across time, and applies rules to identify possible events. A reviewer can inspect each finding, add a note and export a report.

## What you can do

- Upload a short video and draw restricted or passage zones.
- Run local analysis and review a timeline of candidate events.
- Inspect source frames and clips, filter or search events, and save review decisions.
- Explore evaluation results and the system design within the application.
- Export an investigation report as HTML, Markdown or JSON.

## Run locally

The current setup was tested on an Apple M4 Mac using CPU inference. You need Python 3.11, Node.js 20 or later, `uv`, and FFmpeg with H.264 encoding support. The first model download requires an internet connection.

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

Stop the local servers with:

```bash
scripts/dev.sh stop
```

The sample media and local run data are not included in the repository. The media-fetch script downloads two clips; see [third-party notices](THIRD-PARTY-NOTICES.md) for sources and license information.

## Read-only demo

After completing a local run, create a demo bundle with:

```bash
python -m video_investigator.cli export-demo
```

Then open `http://127.0.0.1:5173/?mode=demo`. The demo shows saved results and does not run the model. The bundle is local and ignored by Git. The project is not yet configured for a Vercel deployment.

## How it works

```text
Video → frames → object detection → tracking → event rules
                                               ↓
                              evidence → timeline → human review
```

A FastAPI service manages uploads and runs. One local worker processes video and saves evidence; SQLite stores runs, events and reviews. The React interface displays the recording, timeline and findings. A run is marked complete only after its artifacts are saved.

The current rules flag restricted-zone entry, stationary objects and possible passage occupancy. These are **candidates for review**: image overlap does not prove a physical obstruction, and a stationary object is not automatically unattended.

## Results and limitations

The application uses a pretrained COCO detector and a custom tracking baseline; the model was not trained or fine-tuned in this project. The tracker can lose or split identities, especially in crowded scenes, and the detector can miss or misclassify objects.

The recorded evaluation uses generated fixtures and **two independent real-video recordings**. The real-footage test is very small and was not blind, so its results do not establish performance on new environments. See the Evaluation page and [implementation status](IMPLEMENTATION-STATUS.md) for counts, methods and known gaps. A run with no findings does not certify that a video is incident-free.

SceneTrace does not identify people, determine intent or blame, or make safety-compliance decisions. Semantic embeddings, video-language explanations, cross-camera tracking, model fine-tuning and cloud deployment are not implemented.

## Tests

```bash
python -m pytest
cd web && npm test && npm run build
```

Real-inference tests require the model weights and downloaded clips: `python -m pytest -m real_inference`. They are separate from the offline suite. See [the walkthrough](docs/WALKTHROUGH.md), [parameter ledger](docs/PARAMETER-LEDGER.md), [data card](docs/DATA-CARD.md) and [model card](docs/MODEL-CARD.md) for implementation details.
