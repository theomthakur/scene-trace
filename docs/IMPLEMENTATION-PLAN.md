# Implementation plan: the six pending capabilities

Audit date: 14 November 2026. Baseline at the start: 64 offline Python tests and 14 frontend tests pass, the production build passes, tree clean at `17773d3`, local and `origin/main` equal. Docker CLI is installed but its daemon was not running; there is no Vercel CLI. Everything stays local: nothing is pushed, published or deployed.

## Order and reasons
| # | Item | Priority reason | Planned approach | Known risk |
|---|---|---|---|---|
| 1 | Cloud deployment readiness | Independent, cheap, unblocks a public read-only demo | Demo build mode (`VITE_DEFAULT_MODE=demo`), configurable API base, optional bearer token for non-loopback hosting, Dockerfile and compose for API plus worker, `vercel.json`, deployment doc with storage, resources and cost estimates | Docker daemon is off: image build may be unvalidatable. No deploy without asking. |
| 2 | Semantic search | Highest product value, mostly independent | CLIP ViT-B/32 (MIT) text and image embeddings over event descriptions and evidence frames; structured filters first, semantic ranking second; scores labelled as cosine similarity, never confidence; every hit cites its frame and timestamp | CLIP is coarse; labelled queries are few, so Recall@k is descriptive. |
| 3 | Video-language explanations | Optional layer over (2)'s evidence | Small open VLM (SmolVLM, Apache-2.0) given selected frames and the factual event record; output stored with its evidence, a prompt-hash and a banned-inference check; endpoint returns 503 when the model is unavailable and the UI hides it | CPU latency; a small VLM can hallucinate, so the rubric evaluation will be small and manual. |
| 4 | Fine-tuning | Needs licensed data and compute | CC0 labelled data (`Voxel51/hard-hat-detection`, classes helmet, head, person), deterministic split, fine-tune the detector's box head on CPU, compare with the pretrained baseline on a held-out test with AP50 | Penn-Fudan has no stated licence, so it is excluded. Result may be a small gain or none; it is reported as measured. |
| 5 | Benchmark expansion | Depends on finding suitable licensed fixed-camera footage | Bounded search for CC0 or CC BY fixed-camera clips; add only clips that pass visual and licence checks; keep the used frozen test untouched and add a separate second frozen test | Earlier searches returned mostly police or violent footage: those are excluded on purpose. Expect few additions. |
| 6 | Cross-camera association | Blocked on data for the positive-matching question | Scoped appearance-plus-time association of tracks across two cameras. Real-data evaluation limited to a negative control (two unrelated scenes: every cross-scene association is wrong by construction). Synthetic fixtures for identity switches. No identification claims. | No licensed multi-camera set with enough identities was found (the one CC BY 4.0 re-identification set has 2 identities, from a drone). Positive-match accuracy cannot be reported. |

## Rules for all stages
- Real inference stays real. Synthetic or scripted outputs are tagged `source: fixture` and reported separately.
- New constants go in `docs/PARAMETER-LEDGER.md` with the reason they were chosen.
- `IMPLEMENTATION-STATUS.md` stays local and git-ignored.
- Each stage ends with tests run and results recorded in the relevant doc, including what failed.


## Outcome (14 November 2026)
| # | Item | Result |
|---|---|---|
| 1 | Deployment readiness | Built and checked locally; nothing deployed. See `docs/DEPLOYMENT.md`. Docker image built and smoke-tested on aarch64 only. |
| 2 | Semantic search | Built and tested with the real CLIP model. 8 of 11 labelled queries ranked the right event first. |
| 3 | Descriptions | Built and tested with the real model. Quality is poor (3 of 21 mostly supported); labelled unverified, never alters events. |
| 4 | Fine-tuning | Working, tested path. Held-out test: helmet AP50 0.685, head 0.497 (baseline cannot detect them); person 0.004 against 0.011 (no improvement on the shared class). |
| 5 | Benchmark expansion | 3 additional recordings, 1 annotated event. test-2 is negative-only and the detector found nothing in it. Far short of 12 recordings. |
| 6 | Cross-camera | Workflow, API and synthetic tests done. Real-data negative controls show generic embeddings are a weak basis. True accuracy not measured: no labelled multi-camera data. |
