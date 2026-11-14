# Third-party notices

This repository does **not** redistribute model weights or demonstration video. Weights are downloaded at run time into the user's cache; clips are fetched by `scripts/fetch_demo_media.py` into `var/` (git-ignored). Verify licences yourself before redistributing anything built from this project.

## Demonstration media (fetched, not committed)
| File | Source | Licence as stated on the source page | Redistribution decision |
|---|---|---|---|
| pedestrian_area.webm | https://commons.wikimedia.org/wiki/File:Video_Codec_Test_pedestrian_area_1080p25.y4m.webm (author: Taurus Media Technik, Xiph.org test media, 2013) | CC0 1.0, with a Commons licence-review tag dated 2013-02-20 | Not committed. Fetched on demand and checked against the SHA-1 Commons publishes. |
| rush_hour.webm | https://commons.wikimedia.org/wiki/File:Video_Codec_Test_rush_hour_1080p25.y4m.webm (same author) | CC0 1.0 | Not committed. Same handling. |
| mall_corridor, entrance (reliability batch) | Wikimedia Commons, Ljubljana recordings, author Barbara Rezar Grilc (exact files in `fixtures/benchmark/manifest_reliability.json`) | CC BY 3.0 | Not committed. Fetched on demand; attribution required. |
| platform (reliability batch) | Wikimedia Commons, author Assaf Yekuel (see the same manifest) | CC BY-SA 4.0 | Not committed. Fetched on demand; share-alike applies to any redistribution. |

I relied on the Commons licence statement and review tag. I did not independently verify the upstream Xiph terms. The clips show members of the public in public places and a legible vehicle licence plate in the foreground of rush_hour. The application does not recognise faces or plates and does not identify anyone.

Static-demo bundles exported to `web/public/demo/` (git-ignored) contain frames and a re-encoded copy of a clip. Treat them under the clip's licence and do not publish them without checking.

## Model
| Item | Detail | Status |
|---|---|---|
| Detector | torchvision `fasterrcnn_mobilenet_v3_large_320_fpn`, `COCO_V1` weights. URL https://download.pytorch.org/models/fasterrcnn_mobilenet_v3_large_320_fpn-907ea3f9.pth, SHA-256 `907ea3f91ff92242bc1baea8049276a3e76bca48ce7560bd268cc029f37977b5` | Code is BSD-3-Clause (torchvision). **The licence of the pretrained weights file is not separately stated in the documentation I checked, so it is unresolved.** The weights are not redistributed here. The model was trained on COCO (annotations CC BY 4.0; images subject to their Flickr terms). |

## Python dependencies (versions in `requirements.lock`)
| Package | Licence (from the package metadata, as I understand it) |
|---|---|
| torch, torchvision, scipy, numpy, httpx, uvicorn, Starlette | BSD-3-Clause |
| PyAV | BSD-3-Clause. Its wheels bundle FFmpeg libraries under the LGPL; check the bundled build before redistributing binaries. |
| opencv-python-headless | Apache-2.0. Wheels also bundle FFmpeg (LGPL). |
| FastAPI, SQLAlchemy, Pydantic, PyYAML | MIT |
| python-multipart | Apache-2.0 |
| Pillow | HPND (MIT-style) |
| ffmpeg / ffprobe (system install, used for probing and H.264 derivatives) | LGPL or GPL depending on the build; Homebrew builds with libx264 are GPL. Not bundled here. |

Both PyAV and OpenCV ship their own FFmpeg libraries, so macOS prints an "Class AVFFrameReceiver is implemented in both ..." warning when both are imported. It concerns capture-device classes this project never uses. No crash or wrong output was observed in any test or browser run, but I have not ruled out problems on other platforms.

## Optional models (downloaded on first use; not redistributed here)
| Item | Detail | Licence status |
|---|---|---|
| Semantic search embeddings | `laion/CLIP-ViT-B-32-laion2B-s34B-b79K`, revision `1a25a446712ba5ee05982a381eed697ef9b435cf`, used through `transformers` | Model card metadata: MIT. The model was trained on LAION-2B, a web-scale image collection whose content and rights are not audited here. I chose it over OpenAI's CLIP because the OpenAI model card declares no licence in its metadata. |
| Video-language explanations | `HuggingFaceTB/SmolVLM-500M-Instruct`, revision `753c1752602b5e739af7a7fa6947a635051897a3` | Model card metadata: Apache-2.0. Output is unverified model text; see `docs/evidence/explanation-eval.json` for measured quality. |
| Fine-tuning dataset | `Voxel51/hard-hat-detection` (5,000 images with helmet, head and person boxes; a FiftyOne copy of the Kaggle "Hard Hat Detection" set by andrewmvd, originally from MakeML) | Declared CC0-1.0 by the dataset card. **I could not verify the rights of the underlying photographs.** A 2,000-image deterministic subset is cached on the user's machine, used for training and testing, and never committed or redistributed. |
| Rejected dataset | Penn-Fudan Pedestrian database | Its page grants no licence (only a copyright notice), so it was not used. |

Extra Python dependencies for these features: `transformers`, `huggingface_hub`, `tokenizers`, `safetensors` (Apache-2.0). Docker base images `node:22-slim` (build stage) and `python:3.11-slim` carry their own licences (Node MIT; Python PSF; Debian packages under their respective licences, including FFmpeg built with libx264 under GPL in Debian's build). Not verified in detail: check before distributing an image.

A fine-tuned checkpoint inherits the terms of its base weights (torchvision COCO_V1, unresolved above) and of the training data. It is never committed.

## Frontend (versions in `web/package-lock.json`)
React, React DOM, Vite, @vitejs/plugin-react (MIT); TypeScript (Apache-2.0); Vitest (MIT); puppeteer-core (Apache-2.0, dev only).
