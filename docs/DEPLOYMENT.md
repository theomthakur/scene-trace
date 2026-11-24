# Deployment readiness

Nothing here has been deployed, and no paid service was used or contacted. This describes two ways to host SceneTrace, what was validated locally, and what was not.

| Mode | What it is | Runs a model? | Status |
|---|---|---|---|
| Read-only demo | A static site: the React app plus a precomputed bundle (video, boxes, events, evidence frames and clips). | No | Built into `web/dist-demo` and checked in Brave with the configured headers. |
| Live backend | One container image running the API (which also serves the built UI) and one worker. CPU inference. | Yes | End-to-end verified with Docker Compose on aarch64 Linux. |

## 1. Read-only demo (static)

```bash
scripts/build_demo.sh --run-id <id>     # choose a completed run appropriate for sharing
python scripts/serve_static.py web/dist-demo     # preview at http://127.0.0.1:4173
```
`VITE_DEFAULT_MODE=demo` (set by `npm run build:demo`) makes the app open in the visibly labelled "Static demo" mode with no backend. Upload, zones, processing, review, semantic search and descriptions are disabled or explain that they need the live backend.

The current bundle is 31 MiB. It contains the CC0 pedestrian benchmark video, seven events with their evidence frames and clips, and the saved evaluation reports. A fresh export stages only the selected run, leaving the live UI build and its local data separate. Pass `--skip-clips` to `scripts/build_demo.sh` for a smaller bundle.

The build copies `deploy/vercel/vercel.json` into `web/dist-demo`. The local preview applies its Content-Security-Policy, caching and other headers. The browser checks passed without console errors and a video byte-range request returned HTTP 206. Before publishing, review the selected footage and exported review notes under `web/dist-demo/demo`. Footage attribution is in [third-party notices](../THIRD-PARTY-NOTICES.md).

### Preview on Vercel

1. Build and preview `web/dist-demo` using the commands above. Check the video, evidence and Evaluation page.
2. With the Vercel CLI installed and signed in, run `vercel deploy web/dist-demo` from the repository root and select the intended project. Use the static output directory as the deployment source. [Vercel CLI documentation](https://vercel.com/docs/cli/deploy)
3. Open the preview URL printed by Vercel. Check for the **Static demo** badge, play and seek in the video, and open evidence and the Evaluation page. The static build contains saved results, so it doesn't offer uploads or new analysis.

## 2. Live backend

```bash
export VI_API_TOKEN="$(openssl rand -hex 24)"     # required by docker-compose.yml
docker compose up --build                         # API + UI on 127.0.0.1:8000, plus one worker
```
Open http://127.0.0.1:8000 and enter the token when asked. The compose file binds to loopback only: put an authenticating reverse proxy (TLS, ideally SSO) or a private network in front before exposing it.

**Validated locally on November 23, 2026.** The Compose image built on aarch64 Linux. The API served the UI as uid 10001 and required a token for video routes. In Brave, the API accepted an upload and served an H.264 derivative. The worker processed 75 frames with the pretrained COCO weights (SHA-256 `907ea3f9...`) and returned seven candidate events. Evidence, search, review and report export worked. Restarting both services preserved the completed run, its events and the saved review on the shared volume. JSON, HTML and Markdown exports retained the review, and the JSON retained the source and run hashes.

An x86-64 image, concurrent load, and cloud hosting still need verification if used. The current live setup targets one worker and a private, same-origin service.

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
