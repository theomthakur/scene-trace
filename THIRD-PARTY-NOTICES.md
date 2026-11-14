# Third-party notices

This repository does **not** redistribute model weights or demonstration video. Weights are downloaded at run time into the user's cache; clips are fetched by `scripts/fetch_demo_media.py` into `var/` (git-ignored). Verify licences yourself before redistributing anything built from this project.

## Demonstration media (fetched, not committed)
| File | Source | Licence as stated on the source page | Redistribution decision |
|---|---|---|---|
| pedestrian_area.webm | https://commons.wikimedia.org/wiki/File:Video_Codec_Test_pedestrian_area_1080p25.y4m.webm (author: Taurus Media Technik, Xiph.org test media, 2013) | CC0 1.0, with a Commons licence-review tag dated 2013-02-20 | Not committed. Fetched on demand and checked against the SHA-1 Commons publishes. |
| rush_hour.webm | https://commons.wikimedia.org/wiki/File:Video_Codec_Test_rush_hour_1080p25.y4m.webm (same author) | CC0 1.0 | Not committed. Same handling. |

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

## Frontend (versions in `web/package-lock.json`)
React, React DOM, Vite, @vitejs/plugin-react (MIT); TypeScript (Apache-2.0); Vitest (MIT); puppeteer-core (Apache-2.0, dev only).
