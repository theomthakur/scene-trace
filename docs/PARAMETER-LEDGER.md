# Parameter ledger

Every value is a **provisional engineering default**, not a measured optimum. "Evidence" says what, if anything, was actually measured. The frozen test split was not used to choose any of these.

| Parameter | Value | Units | Rationale | Evidence and known failure cases |
|---|---|---|---|---|
| upload limit | 250 MiB, 300 s | bytes, s | local resource budget | Enforced while streaming (413) and again after probing. Tested with a 2,000-byte cap. |
| processing long edge | 960 | px | bound memory and time | Not measured against small-object loss. The detector resizes internally to 320 to 640 px anyway. |
| sample rate | 5 | frames/s | initial fixed-camera default | Development sweep on one clip (see below). 2 fps found 0 of 2 events; 5 fps found 1; 10 fps found 2 but took 17.4 s against 6.4 s. One clip, two events: no optimum can be claimed. |
| detector threshold | 0.50 | score | precision-oriented start | Sweep: 0.30 gave 179 tracks, 0.50 gave 117, 0.70 gave 76 and found both events with no false positive. **Not adopted** because two events cannot justify tuning. |
| tracker IoU gate | 0.20 | IoU | permissive start | Not swept. In the crowded pedestrian clip the tracker made about 117 tracks for roughly 9 people per frame: identities fragment. |
| missing-track lifetime | 1.0 | s | short occlusion tolerance | A track missing longer ends before matching and is never revived (a unit test caught a bug where it could be). |
| min hits to confirm | 2 | hits | suppress one-frame false detections | Added constant. Only confirmed observations feed the event rules. |
| velocity smoothing | 0.5 | EMA weight | damp noisy box motion | Added constant, not tuned. |
| zone-entry dwell | 1.0 | s | suppress momentary boundary noise | Fixtures: a 0.8 s crossing is suppressed; exactly 1.0 s fires (equality counts). |
| max qualifying gap | 0.4 | s | joint with sample rate (must be at least 1/fps; validated) | Fixtures: gap equal to the limit bridges, longer breaks. At 2 fps it must be 0.5 s (override used in the sweep). |
| exit hysteresis | 0.4 | s | stop boundary flicker from splitting or creating events | Added constant. Bridged time never counts as dwell. Fixture "flicker" shows alternating in/out produces no event. |
| stationary duration | 5.0 | s | visible demo persistence | Not an operational safety standard. |
| stationary displacement | 0.02 | image diagonal | normalise pixel motion | Compared with the window start anchor, not the previous frame, so slow creep is movement. Perspective can fool it. |
| passage overlap | 0.30 | fraction of box area | 2D candidate criterion | Not physical clearance. |
| passage persistence | 2.0 | s | suppress brief overlap | Not swept. |
| evidence padding | 3.0 | s | reviewer context | Clamped to the video bounds. |
| search limit | 10, max 50 | results | bounded response | No relevance score exists. |
| quality: sparse detections | 0.05 | detections per sampled frame | flag runs that probably saw nothing | Added constant, not tuned. |
| quality: long gap factor | 3.0 | sampling periods | flag timing holes | Added constant, not tuned. |
| edge-of-video flag margin | 1.5 | sampling periods | mark events that start or end at the clip edge | Added constant. |
| evidence frame tolerance | 250 | ms | pick the nearest decoded frame | Added constant. Evidence frame times are snapped to observation times, so a drawn box always has a stored observation. |
| UI overlay tolerance | 1.25 x median sample gap | ms | never paint boxes on a frame they do not belong to | Added constant; unit-tested. |
| evaluation temporal IoU | 0.5 | IoU | declared matching rule | One-to-one greedy by IoU. |

## Development sweep (one clip, 2 annotated events; run once, descriptive)
| Setting | Tracks | Detections | Events | Matched / false / missed | Seconds |
|---|---|---|---|---|---|
| 2 fps | 79 | 251 | 0 | 0 / 0 / 2 | 2.3 |
| 5 fps, 0.50 (default) | 117 | 651 | 2 | 1 / 1 / 1 | 6.4 |
| 10 fps | 146 | 1290 | 3 | 2 / 1 / 0 | 17.4 |
| 5 fps, 0.30 | 179 | 822 | 2 | 1 / 1 / 1 | 5.1 |
| 5 fps, 0.70 | 76 | 541 | 2 | 2 / 0 / 0 | 5.7 |

The configuration was frozen (`fixtures/benchmark/FREEZE.json`, committed before the test split ran) with the defaults unchanged.
