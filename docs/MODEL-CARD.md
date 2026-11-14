# Model card

**Detector:** torchvision `fasterrcnn_mobilenet_v3_large_320_fpn`, `COCO_V1` weights (SHA-256 `907ea3f91ff92242bc1baea8049276a3e76bca48ce7560bd268cc029f37977b5`). Used as published: `eval()` mode, inference mode, no training or fine-tuning. Chosen for manageable complexity, not best accuracy.

**Classes used:** person, bicycle, car, motorcycle, bus, truck, backpack, handbag, suitcase (a subset of the 91 COCO categories). Other objects, including packages and warehouse items, are not reliably detected.

**Measured here (one Apple M4, CPU, torch 2.15.0, torchvision 0.29.2):** about 73 ms per sampled 960 px frame; 75 sampled frames of the 15 s pedestrian clip in about 5.6 s (2.6x real time); the 20 s rush-hour clip in about 8 s. Repeated runs on this machine gave byte-identical observations. MPS and CUDA are opt-in and were not used.

**Known weaknesses seen:** under heavy crowding the baseline tracker made about 117 tracks for roughly 9 people per frame at 5 fps in a crowded clip (identity splits and switches are possible but unmeasured, since no ground-truth tracks exist; in the frozen test no duplicate tracks of one car were found); partially cropped people near the frame edge have unreliable ground contact.

**Tracker:** custom per-class constant-velocity prediction over real elapsed time, IoU gate 0.20, Hungarian assignment (`scipy.optimize.linear_sum_assignment`), tentative, confirmed, lost and ended states, IDs never recycled, no re-identification.

**Intended use:** assist a human reviewer inspecting footage. **Not for:** enforcement, identification, intent or compliance decisions, or any claim of incident-free video.


## Added models and workflows
**Semantic search:** `laion/CLIP-ViT-B-32-laion2B-s34B-b79K` (MIT per its card), 512-d embeddings of evidence frames and tracked-object crops, CPU, 0.8 GB peak. Measured: 8 of 11 labelled queries ranked the right event first. Weak spots: small objects inside a large crop ("person leaning out of a car window") and near-duplicate vehicles. Scores are cosine similarities: a ranking aid, not a confidence.

**Descriptions:** `HuggingFaceTB/SmolVLM-500M-Instruct` (Apache-2.0), one crop per request, greedy decoding. Of 21 descriptions rated against the frame: 3 mostly supported, 12 mixed, 6 mostly unsupported; 17 invented some detail; it said it could not tell once. It reads text such as plates aloud (redacted by the platform). Several images at once made it hallucinate much more. Treat its output as an unverified hint.

**Cross-camera association:** candidate links from timing plus appearance. With generic CLIP crop embeddings, at 0.85 similarity 57% of different people visible together in one scene would be falsely linked (pedestrian clip) while 79% of same-track halves link; at 0.95 false links fall to 4% but almost nothing links. True cross-camera accuracy is not measured. These embeddings are not person re-identification features.

**Fine-tuned detector (opt-in):** Faster R-CNN MobileNetV3-Large FPN, COCO-pretrained, box predictor replaced with helmet, head and person (person warm-started from COCO), backbone trained, 416 px, SGD, 6 epochs, seed 7, on a 1,000-image subset of a declared-CC0 dataset. Held-out test AP50: helmet 0.685, head 0.497, person 0.004 (pretrained baseline: cannot detect helmet or head; person 0.011). It no longer reports COCO classes like car or bicycle.
