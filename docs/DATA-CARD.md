# Data card

## Sources
Two CC0 test sequences by Taurus Media Technik (Xiph.org), hosted on Wikimedia Commons. Fetched by `scripts/fetch_demo_media.py`, SHA-1 verified, never committed.

| Clip | Scene | Duration | Size | Split |
|---|---|---|---|---|
| pedestrian_area | Munich pedestrian zone, static low camera, dense foot traffic | 15.1 s | 1920x1080, 25 fps, VP8 in WebM (timestamps in milliseconds) | development |
| rush_hour | Munich traffic jam, fixed camera, many cars, almost no people | 20.1 s | 1920x1080, 25 fps | test |

Splits are by source scene: no scene appears in both. The brief's goal was twelve recordings (six and six). **Only two exist, so nothing here is statistically adequate.**

## Annotations
`fixtures/benchmark/manifest.json` holds hashes, licences, scene IDs, zone files and annotated events.
- **Method:** one reviewer (the implementing assistant) looked at raw decoded frames every 0.4 s with only the zone outline drawn, and wrote visibility intervals rounded to 0.4 s. This is not expert consensus.
- **Contamination:** I had already seen detector event lists for both clips while building the pipeline, so the test split is **not blind**.
- **Annotated:** (development) a man standing in a doorway, two visibility intervals, and an upper-left zone where nobody walks (negative); (test) a red car that stays in place all clip, and a people-only strip with no people (negative).
- **Not annotated:** boxes, tracks, the many people crossing the pedestrian clip (ground contact cannot be judged reliably under heavy occlusion and cropped foreground people), passage events, stationary bicycles. Detection and tracking metrics are therefore "not evaluated".
- **Matching:** same type and zone, temporal IoU of at least 0.5, one-to-one. Undefined ratios are reported as null with a reason.

## Fixtures
`src/video_investigator/evaluation/fixtures.py` generates 12 scenarios of scripted observations with deterministic truth (empty, boundary grazing, flicker, occlusion gap, stationary with jitter, overlapping rules, frame-rate change, tentative-only, no merge across tracks). They test the temporal rules without a detector, are tagged `source: fixture` everywhere, and say nothing about real video. `fixtures/reports/fixture-report.json` is reproduced byte for byte by a test.

## Privacy and ethics
The clips show people in public places and a legible licence plate. Track IDs are temporary labels within one run. No face recognition, plate reading or re-identification exists in the code.
