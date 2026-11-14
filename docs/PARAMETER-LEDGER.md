# Parameter ledger

Every value is a **provisional engineering default**, not a measured optimum. "Evidence" says what, if anything, was actually measured. The frozen test split was not used to choose any of these.

| Parameter | Value | Units | Rationale | Evidence and known failure cases |
|---|---|---|---|---|
| upload limit | 250 MiB, 300 s | bytes, s | local resource budget | Enforced while streaming (413) and again after probing. Tested with a 2,000-byte cap. |
| processing long edge | 960 | px | bound memory and time | Not measured against small-object loss. The detector resizes internally to 320 to 640 px anyway. |
| sample rate | 5 | frames/s | initial fixed-camera default | Development sweep on one clip (see below). 2 fps found 0 of 2 events; 5 fps found 1; 10 fps found 2 but took 17.4 s against 6.4 s. One clip, two events: no optimum can be claimed. |
| detector threshold | 0.50 | score | precision-oriented start | Sweep: 0.30 gave 179 tracks, 0.50 gave 117, 0.70 gave 76 and found both events with no false positive. **Not adopted** because two events cannot justify tuning. |
| tracker IoU gate | 0.20 | IoU | permissive start | Not swept. In the crowded pedestrian clip the tracker made about 117 tracks for roughly 9 people per frame; no ground-truth tracks exist, so how many of these are identity splits is not measured. |
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


# Added for semantic search, descriptions, cross-camera association, fine-tuning and deployment

Same rule as above: provisional engineering defaults, not tuned optima, unless the evidence column says something was measured. None of these touched the frozen detector benchmark (its config hash is unchanged, and a test checks that).

## Semantic search
| Parameter | Value | Why | Evidence and known failure cases |
|---|---|---|---|
| embedding model | `laion/CLIP-ViT-B-32-laion2B-s34B-b79K`, revision `1a25a446...` | small enough for CPU; the model card states MIT (OpenAI's CLIP card declares no licence) | 11 labelled queries over 21 events: 8 of 11 have a relevant event at rank 1 (hybrid), 10 of 11 within the top 3; time-ordered class filtering gets 2 of 11 at rank 1. Failures: "person leaning out of a car window" (rank 7: the person is a small part of a car crop) and several that put the right event at rank 2 ("person with a backpack", "silver van"). |
| indexed items | evidence frames (start, mid, end) plus a crop of each tracked box on those frames | the crop makes object-level queries ("red car") possible; the frame keeps context | Crops under 24 px are skipped. Only saved evidence frames are indexed, not every video frame, so an object that never became an event cannot be found. |
| crop padding | 0.10 of the box | include a little context | Not tuned. |
| similarity threshold | none by default; optional `min_similarity` | raw CLIP scores sit in a narrow band (0.20 to 0.33 for top hits here) and mean different things per query, so a fixed cutoff would be arbitrary | Scores are always labelled as a ranking aid, never a confidence. |
| result limit | 10 default, 50 max (same as keyword search) | bounded response | |
| structured filter | applied before ranking; explicit filters replace words found in the text | an explicit choice must win over a guess | Unit-tested. |

## Descriptions (video-language)
| Parameter | Value | Why | Evidence and known failure cases |
|---|---|---|---|
| model | `HuggingFaceTB/SmolVLM-500M-Instruct`, revision `753c1752...`, fp32, CPU | smallest instruction-tuned VLM that runs locally and is Apache-2.0 | 21 descriptions rated by one reviewer: 3 mostly supported, 12 mixed, 6 mostly unsupported; invented detail in 17; said "cannot tell" in 1. Automatic flags caught 8 of the 17 bad ones. |
| default frames | one: the middle evidence frame | a pilot showed three crops at once made the model hallucinate a brand name and invent scenes | Multi-frame use is allowed but always flagged. |
| image edge | 512 px, no image splitting | speed: about 1.4 s per description | 768 px was not clearly better in a small pilot. |
| decoding | greedy, 110 new tokens, repetition penalty 1.15 | reproducible output; the penalty stopped label parroting in the pilot | Prompt wording was chosen after a pilot on 4 of the 21 events, so those 4 are not an untouched test. |
| prompt | one neutral question about the crop; the event record is NOT fed to the model | a pilot showed the model repeats times and labels it is given | |
| checks | inference words, times outside the evidence, supported classes the detector did not report, uninformative text, degenerate output, identifier redaction | cheap guards, not verification | 8 of 17 bad descriptions flagged; 2 flags were on descriptions I rated acceptable. Identifier-like strings (a licence plate was read aloud in the pilot) are removed before storage. |

## Cross-camera association
| Parameter | Value | Why | Evidence and known failure cases |
|---|---|---|---|
| similarity threshold | 0.95 | with generic CLIP crop embeddings, 0.85 falsely links 57% of co-visible different people (pedestrian clip) and 0.90 still 29%; about 0.95 is where that falls to 4% | At 0.95 only 2% of same-track halves link on the pedestrian clip (45% for cars), so the tool proposes very little by design. Appearance alone is not a basis for linking people. |
| margin over runner-up | 0.03 | refuse ambiguous matches instead of guessing | Unit-tested; not tuned on real data. |
| time gap window | 0 to 60 s, caller-overridable; the clock offset between cameras is required, never guessed | gating removes physically impossible links | |
| crops per track | up to 6, mean-pooled; tracks need at least 3 confirmed observations | stabilise the descriptor | |

## Fine-tuning
| Parameter | Value | Why | Evidence and known failure cases |
|---|---|---|---|
| data | `Voxel51/hard-hat-detection`, 2,000-image deterministic subset: 1,000 train, 200 validation, 800 test | declared CC0; ordered by SHA-256 of file name so the split is identical on any machine | person boxes are scarce (169 train, 16 validation, 111 test) |
| trained parameters | box predictor, RPN and ROI heads; backbone frozen in the first run | CPU budget and small data | see the trial table below |
| optimiser | SGD, momentum 0.9, weight decay 5e-4, cosine decay | standard detection fine-tuning recipe | not searched |
| epochs, batch, seed | 6, 8, 7 | five minutes per run on CPU | one seed: run-to-run variance is not estimated |
| model selection | best validation mAP50 epoch | uses validation only | selection among trials and epochs makes validation scores optimistic; the test split is evaluated once |

### Fine-tuning development trials (validation only; the test split was not touched until the configuration was frozen)
| Trial | Image size | Backbone | LR | Best validation mAP50 | helmet / head / person AP50 |
|---|---|---|---|---|---|
| v1 | 320 (the detector's default) | frozen | 0.01 | 0.253 | 0.42 / 0.33 / 0.007 |
| v2 | 416 (native) | frozen | 0.01 | 0.347 | 0.56 / 0.47 / 0.013 |
| **v3 (selected)** | 416 (native) | **trained** | 0.005 | **0.432** | 0.67 / 0.59 / 0.038 |

Three configurations were tried, so the validation score of the selected one is somewhat optimistic. Choice reasons: v1 downsized 416 px images to 320, shrinking small helmets, so v2 used native size; v2's frozen backbone limited what the heads could learn, so v3 trained everything at a lower learning rate. The pretrained baseline's validation person AP50 was 0.021 on 16 boxes.

**Held-out test (800 images, evaluated once, checkpoint `ed84da37...`, frozen in `fixtures/finetune/FREEZE.json` before the run):**
| Class | Boxes | Fine-tuned AP50 | Pretrained baseline AP50 |
|---|---|---|---|
| helmet | 2,881 | 0.685 | cannot detect (not a COCO class) |
| head | 967 | 0.497 | cannot detect (not a COCO class) |
| person | 111 | 0.004 | 0.011 (difference -0.007, 95% bootstrap over images -0.022 to -0.001) |

Reading it plainly: fine-tuning gave the detector two classes it did not have, at moderate accuracy (that is expected by construction, not a sign of a better detector). On the only class both models share, the fine-tuned model was not better and was slightly worse, with both near zero on this dataset's unusual "person" boxes. One seed and one split: no run-to-run variance is estimated. The fine-tuned model also stops reporting COCO classes such as car and bicycle, so it is a worksite specialist, not a replacement. It was **not** evaluated on the benchmark video clips (no matching annotations), so nothing is claimed about its effect on SceneTrace's events.
