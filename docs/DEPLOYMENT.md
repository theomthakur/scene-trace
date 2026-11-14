# Deployment readiness

Nothing here has been deployed, and no paid service was used or contacted. This describes two ways to host SceneTrace, what was validated locally, and what was not.

| Mode | What it is | Runs a model? | Status |
|---|---|---|---|
| Read-only demo | A static site: the React app plus a precomputed bundle (video, boxes, events, evidence frames and clips). Suited to Vercel or any static host. | No | Built and checked in a real browser under the production headers. Not deployed. |
| Live backend | One container image running the API (which also serves the built UI) and one worker. CPU inference. | Yes | Image built and smoke-tested locally (aarch64 Linux). Not deployed. |

## 1. Read-only demo (static)

```bash
scripts/build_demo.sh            # exports the latest completed local run, then builds web/dist in demo mode
python scripts/serve_static.py web/dist     # preview at http://127.0.0.1:4173 with the production headers
```
`VITE_DEFAULT_MODE=demo` (set by `npm run build:demo`) makes the app open in the visibly labelled "Static demo" mode with no backend. Upload, zones, processing, review, semantic search and descriptions are disabled or explain that they need the live backend.

**Measured:** the bundle exported from the benchmark pedestrian run is 35 MB (34 MB under `demo/`): a 3.4 MB re-encoded video, 7 events with evidence frames, and 7 padded clips that account for most of the size. The largest single file is the video or a clip; the JS is 268 kB (83 kB gzipped). `python -m video_investigator.cli export-demo --skip-clips` leaves out the clips for a smaller bundle. I did not look up Vercel's current file and deployment size limits, so check them before deploying a bundle this size.

**Headers** (`deploy/vercel/vercel.json`, copied into `web/dist/` by the build script): a strict Content-Security-Policy (`default-src 'self'`, no inline scripts or styles, `frame-ancestors 'none'`), `nosniff`, no referrer, no camera, microphone or location, long caching for hashed assets and one hour for `/demo/`. The static check (`web/e2e/demo.mjs` with `DEFAULT_DEMO=1`) loads the build from a server that applies exactly these headers and requires zero console errors, so a CSP violation would fail it. Range requests (video seeking) were verified to return 206.

**Deploying it later (not done):** `vercel deploy web/dist` after `vercel login`. The bundle contains frames from a CC0 clip showing members of the public; confirm you are comfortable publishing that. The licence notes are in `THIRD-PARTY-NOTICES.md`.

## 2. Live backend

```bash
export VI_API_TOKEN="$(openssl rand -hex 24)"     # required by docker-compose.yml
docker compose up --build                         # API + UI on 127.0.0.1:8000, plus one worker
```
Open http://127.0.0.1:8000 and enter the token when asked. The compose file binds to loopback only: put an authenticating reverse proxy (TLS, ideally SSO) or a private network in front before exposing it.

**Validated locally:** `docker build` succeeded (image 2.84 GB, Python 3.11, CPU PyTorch 2.15.0, H.264 encoder present); its health endpoint answers, it returns 401 without the token and 200 with it, serves the built UI, runs as a non-root user (uid 10001), and the detector loaded the same COCO weights (SHA-256 `907ea3f9...`). The compose file validates (`docker compose config`). **Not validated:** an x86-64 build (the daemon here is aarch64), a full upload and processing run inside the container, multi-container volume sharing between API and worker under load, and any cloud provider.

**Hosting the frontend and backend separately** is not supported yet: the optional access token uses a same-site cookie, so the UI and API must share an origin. The build does accept `VITE_API_BASE` and the API accepts `VI_CORS_ORIGINS`, but cross-site cookie authentication (`SameSite=None; Secure`, credentialed CORS) is not implemented. The supported split is: static demo on Vercel, live service on its own host and URL.

### Configuration
| Variable | Where | Meaning |
|---|---|---|
| `VI_API_TOKEN` | backend | If set, every `/api` route except health and session needs the token (bearer header or the cookie set by `POST /api/session`). Unset means open, which is only safe on loopback. |
| `VI_DATA_DIR` | backend | Uploads, runs, evidence and the SQLite database (default `./var`; `/data` in the image). Must be a local disk, not a network share (SQLite WAL). |
| `VI_WEB_DIST` | backend | Directory of the built UI to serve at `/` (set in the image). |
| `VI_CORS_ORIGINS` | backend | Comma-separated allowed origins (default: the local Vite dev origins). |
| `VI_UPLOAD_MAX_BYTES` | backend | Overrides the 250 MiB default upload limit. |
| `VI_LEASE_SECONDS` | worker | Job lease; a worker silent for this long is treated as lost (default 30). |
| `VI_EXPERIMENTAL_CROSSCAM` | backend | Default `off`: the cross-camera endpoint returns 404. Set `on` only to experiment; it is unvalidated. |
| `VI_SEMANTIC`, `VI_EXPLAIN` | backend | `off` disables semantic search or descriptions (they return 503 and the rest of the app is unaffected). |
| `VI_DETECTOR_CHECKPOINT` | worker | Opt-in fine-tuned detector weights. Recorded in every run; not part of the config hash. |
| `TORCH_HOME`, `HF_HOME` | backend, worker | Where model weights are cached (`/data/torch`, `/data/hf` in the image, so they survive restarts). |
| `VITE_DEFAULT_MODE`, `VITE_API_BASE` | frontend build | `demo` makes the build open in static-demo mode; `VITE_API_BASE` points the UI at another API origin (see the limitation above). |

### Storage
- **Database:** SQLite in WAL mode: runs, events, reviews, explanations. About 1.1 MB after the benchmark runs and many test reviews. A single writer process model: one worker.
- **Per video:** the original (kept byte-identical), a playable H.264 copy (3.4 MB for the 11.2 MB benchmark clip), and per run an `attempt-N/` folder. Measured: 27 MB for 7 events on the 15 s pedestrian clip and 53 MB for 14 events on the 20 s traffic clip. Padded evidence clips dominate (roughly 4 MB per event); observations are small (152 kB for 651 boxes).
- **Models (downloaded on first use):** detector 78 MB (PyTorch hub), semantic embeddings about 0.6 GB, descriptions about 1 GB (Hugging Face cache). Keep `/data` on a persistent volume so these are not re-downloaded.
- **Not built:** retention or cleanup of old runs, and backups. Back up the data directory with the application stopped, or use `sqlite3 app.db ".backup"` for the database.

### Resources (measured on an Apple M4 laptop, CPU, 16 GB; peak resident memory from `/usr/bin/time -l`)
| Workload | Measured |
|---|---|
| Detection pipeline on the 15 s 1080p clip | about 73 ms per sampled frame (5 per second); 75 frames in about 5.6 s uncontended (2.6x real time); peak memory 0.81 GB |
| Semantic index and query | model load 2.9 s, 8 crops in 0.6 s; peak memory 0.82 GB |
| Description (SmolVLM-500M) | load 3.3 s, 1.4 s mean per description over 21 events; peak memory 2.3 GB |
| Image | 2.84 GB on disk |

Rule of thumb from those numbers, for planning only: one worker needs about 1 GB for processing, about 3.5 GB if the description model is also loaded, plus room for uploads. Throughput on a cloud CPU was **not measured**; it will differ from this laptop, and I would measure before promising any turnaround time.

### Costs
I did **not** look up current prices for any provider, so there are no dollar figures to rely on here. What can be computed from measurements: processing cost per hour of video = (hours of compute needed per hour of video) x (your instance's price per hour). On the M4 the detector ran at about 2.6x real time at 5 sampled frames per second, so about 0.4 compute-hours per video-hour at that rate; a cloud vCPU is likely slower, so measure on the instance you choose. Storage is dominated by evidence clips (roughly 4 MB per event) plus the original upload. A static demo host typically costs little or nothing for a 35 MB bundle, but check the provider's current limits and terms.

## 3. Security notes
- Single-user prototype: one shared token, no accounts, no per-user data separation, no audit log of access.
- Always put TLS in front of a non-loopback deployment. The session cookie is `HttpOnly` and `SameSite=Lax`, and is marked `Secure` when the request arrives over HTTPS.
- Uploads are size-limited while streaming, probed before processing, stored under generated names, and never served by path.
- Videos can show identifiable people. The application does not recognise faces or plates (descriptions that read a plate are redacted), but a deployment still needs a retention policy and a lawful basis for the footage it holds.
