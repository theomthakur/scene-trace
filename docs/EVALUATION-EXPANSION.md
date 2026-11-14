# Benchmark expansion

The original benchmark (two recordings, frozen test split used once) is untouched: its manifest, freeze record and results are byte-identical and a test checks that. The additional recordings below live in `fixtures/benchmark/manifest_expansion.json`, with their own development set, their own separately frozen test set (`FREEZE-2.json`, committed before the detector ran on it) and their own once-only guard. They are not pooled with the first benchmark.

## How candidates were found
`scripts/harvest_commons_candidates.py` searched Wikimedia Commons with 20 queries (traffic, crossings, stations, escalators, squares and so on) and kept only CC0, public-domain, CC BY and CC BY-SA files of 6 to 90 s, dropping titles that suggest violence, crime, disasters or children. That left 145 candidates; a handful of sensitive ones slipped past the title filter and were ignored by hand. I viewed poster frames and downloaded 10 plausible clips with SHA-1 verification, then tested each for a fixed camera with `scripts/check_fixed_camera.py` (median whole-frame phase-correlation shift between frames one second apart; the first benchmark clips score about 0.45 px). Only **three** of the ten were fixed enough (median under 1 px): the Washington DC crosswalk (0.04 px), the Roncesvalles crossing (0.16 px) and the aerial roundabout (0.2 px). Measured and rejected as handheld or shaky: three Illinois intersection views (9 to 17 px), the Gdańsk station hall (20.8 px), the Montréal intersection (2.1 px with large excursions), the Tjumeno crossing (1.9 px) and a Saint Anthony Street crossing (4.5 px). Others on the shortlist (such as a Hedemora crossing filmed from a moving car) were dropped from their poster frames without downloading.

## What was added
| Set | Recording | Licence | Length | Annotated events | Units |
|---|---|---|---|---|---|
| development-2 | Roncesvalles Ave pedestrian crossing, Toronto | CC BY-SA 4.0 | 13.1 s | 1 (a pedestrian in the right sidewalk zone, 11.0 to 13.1 s) | 1 positive |
| development-2 | Washington DC crosswalk | CC BY 3.0 | 62.8 s | 0 | 1 negative |
| test-2 (frozen) | Aerial roundabout (14/61) | CC0 | 36.4 s | 0 | 1 negative |

Totals: development-2 is 2 recordings, 75.8 s, 1 annotated event; test-2 is 1 recording, 36.4 s, no annotated events. Annotation method as in the first benchmark: one reviewer, raw frames with only the zone outline, visibility intervals. The queued vehicles in the Roncesvalles clip were **not** annotated because their stationarity cannot be judged reliably from the frames.

## Results (descriptive: these are 1 event and about 0.03 hours of negative video)
| Set | Matched / false / missed | Precision | Recall | False alerts per negative-video hour | Notes |
|---|---|---|---|---|---|
| development-2 | 1 / 0 / 0 | 1 of 1 | 1 of 1 | 0 over 0.017 h | predicted 10.8 to 12.4 s against truth 11.0 to 13.1 s: temporal IoU 0.69, onset error 173 ms |
| test-2 | 0 / 0 / 0 | undefined (no predicted events) | undefined (no annotated events) | 0 over 0.010 h | **the detector found nothing at all** (0 detections in 182 sampled frames; run flagged `sparse_detections`) |

## Failure cases and what they mean
- **Aerial roundabout (test-2):** vehicles are 15 to 30 px tall in the working frame, below what this small detector finds. The 0.0 false alerts are vacuous: a blind detector cannot raise a false alert. This is exactly the "no events is not an incident-free video" case; the quality flag is the only warning, so reviewers must read it.
- **Washington DC:** 62.8 s with 9 tracks and only 20 detections; the street is nearly empty, so it mostly tests that nothing spurious fires. It did not.
- **Roncesvalles:** a person partly hidden behind a pole was tracked well enough to match, but the interval ended 0.7 s early (track lost behind the pole).
- The no-persistence baseline raised no extra alerts on development-2 because these scenes are so empty; the persistence logic is only stressed by busy scenes (the first benchmark's baseline made 177 false alerts on the traffic clip).

## What is blocked and why
More positives need annotated, fixed-camera, openly licensed footage of people or vehicles. Most Commons results were handheld, sensitive, or removed by the licence and duration filters, and Wikimedia rate-limited the downloads heavily. Two further sets I considered (a light-rail platform and a TRAX station) did not finish downloading, so they were not evaluated. Twelve recordings (the original goal) would need either more search, a footage donation, or consented recordings.

Reproduce: `python scripts/fetch_candidates.py 98 83 100` (uses `var/candidates/harvest.json` from the harvest script), then `python -m video_investigator.cli evaluate-expansion` (and, once only, `--include-test2`).
