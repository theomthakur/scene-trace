# Model card

**Detector:** torchvision `fasterrcnn_mobilenet_v3_large_320_fpn`, `COCO_V1` weights (SHA-256 `907ea3f91ff92242bc1baea8049276a3e76bca48ce7560bd268cc029f37977b5`). Used as published: `eval()` mode, inference mode, no training or fine-tuning. Chosen for manageable complexity, not best accuracy.

**Classes used:** person, bicycle, car, motorcycle, bus, truck, backpack, handbag, suitcase (a subset of the 91 COCO categories). Other objects, including packages and warehouse items, are not reliably detected.

**Measured here (one Apple M4, CPU, torch 2.15.0, torchvision 0.29.2):** about 73 ms per sampled 960 px frame; 75 sampled frames of the 15 s pedestrian clip in about 5.6 s (2.6x real time); the 20 s rush-hour clip in about 8 s. Repeated runs on this machine gave byte-identical observations. MPS and CUDA are opt-in and were not used.

**Known weaknesses seen:** under heavy crowding the baseline tracker fragments identities (about 117 tracks for roughly 9 people per frame at 5 fps); a car that stays still produced two track fragments; partially cropped people near the frame edge have unreliable ground contact.

**Tracker:** custom per-class constant-velocity prediction over real elapsed time, IoU gate 0.20, Hungarian assignment (`scipy.optimize.linear_sum_assignment`), tentative, confirmed, lost and ended states, IDs never recycled, no re-identification.

**Intended use:** assist a human reviewer inspecting footage. **Not for:** enforcement, identification, intent or compliance decisions, or any claim of incident-free video.
