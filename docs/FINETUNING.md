# Fine-tuning workflow

Reproducible on one laptop CPU. Data: `Voxel51/hard-hat-detection` (declared CC0-1.0; see `THIRD-PARTY-NOTICES.md` for the caveats). Split: deterministic, by SHA-256 of the file name, 1,000 train / 200 validation / 800 test.

```bash
python -m video_investigator.training.finetune prepare                      # split manifest + download the 2,000 images (about 520 MB, cached)
python -m video_investigator.training.finetune train --name hardhat-v3-416-unfrozen --image-size 416 --unfreeze-backbone --lr 0.005
python -m video_investigator.training.finetune freeze --name hardhat-v3-416-unfrozen     # records checkpoint and split hashes
git add fixtures/finetune && git commit -m "freeze before test"             # the order that was followed
python -m video_investigator.training.finetune evaluate --name hardhat-v3-416-unfrozen --include-test   # once; a second run is refused
VI_DETECTOR_CHECKPOINT=var/models/hardhat-v3-416-unfrozen/checkpoint.pt  # opt-in use in the app (set classes in the run config)
```

## What was done and what was found
1. Three configurations were tried on the **validation** split (table in `docs/PARAMETER-LEDGER.md`): validation mAP50 0.253, 0.347, 0.432. The third (native 416 px, backbone trained, lr 0.005) was selected.
2. The selection, checkpoint hash and split hash were recorded in `fixtures/finetune/FREEZE.json` and committed **before** the test split was evaluated. The test split was then evaluated once (`docs/evidence/finetune-test.json`); the runner refuses a second evaluation and refuses a checkpoint that differs from the frozen one.
3. Held-out test AP50: helmet 0.685 (2,881 boxes) and head 0.497 (967), which the pretrained baseline cannot detect at all; person 0.004 against the baseline's 0.011 (111 boxes; difference -0.007, 95% bootstrap over images -0.022 to -0.001).

## How to read this
- The helmet and head gains exist by construction: COCO has no such classes. They show that the training path works and what accuracy a CPU fine-tune of 1,000 images reaches, not that the model is a better detector.
- The only fair comparison is **person**, and there the fine-tuned model was not better. Person boxes in this dataset are rare and unusual (the pretrained model also scores near zero), so that comparison says little.
- One seed, one split, three trials on the validation set (so validation numbers are optimistic), CPU only. No variance estimate.
- It was not evaluated on SceneTrace's benchmark clips (no matching annotations), so there is no claim about its effect on events. It specialises the detector to worksite classes and drops COCO's car, bicycle and others.
- What blocked a stronger study: no licensed labelled data in the product's own domain (indoor aisles, warehouses), and a CPU-only budget. A larger or more relevant dataset, several seeds and GPU time would be the next step.

## Tests
`tests/test_training.py` runs offline on a randomly initialised model with synthetic images: AP maths (perfect, missed, duplicate, threshold equality, undefined without truth), deterministic split, a real two-epoch training loop (finite loss, only trainable parameters change, backbone untouched when frozen), checkpoint round-trip, the COCO person-row warm start, the opt-in detector checkpoint, and the once-only guard. These test the path, not accuracy.
