"""Fine-tuning data: Voxel51/hard-hat-detection (declared CC0-1.0 by its publishers; 5,000 images of 416x416 with helmet, head and person boxes).

Provenance caveat: the dataset card says CC0 and points to a Kaggle/MakeML collection. The rights of the underlying photographs are not verified here.
Images are downloaded to the Hugging Face cache on the user's machine and never committed or redistributed.

The split is deterministic: images are ordered by SHA-256 of their file name and the first N are assigned to train, then validation, then test. No random
number generator is involved, so every machine gets the same split. The test images are used for one final comparison only.
"""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

REPO_ID = "Voxel51/hard-hat-detection"
CLASSES = ["helmet", "head", "person"]                 # label ids 1..3 (0 is background)
SPLIT_SIZES = {"train": 1000, "val": 200, "test": 800}
MANIFEST = Path(__file__).resolve().parents[3] / "fixtures" / "finetune" / "split_manifest.json"


@dataclass
class Item:
    file: str                    # "data/hard_hat_workersNNN.png" inside the dataset repo
    width: int
    height: int
    boxes: list[list[float]]     # pixel xyxy
    labels: list[int]            # 1..3


def load_items() -> list[Item]:
    from huggingface_hub import hf_hub_download
    d = json.load(open(hf_hub_download(REPO_ID, "samples.json", repo_type="dataset")))
    out = []
    for s in d["samples"]:
        w, h = s["metadata"]["width"], s["metadata"]["height"]
        boxes, labels = [], []
        for det in s["ground_truth"]["detections"]:
            if det["label"] not in CLASSES:
                continue
            x, y, bw, bh = det["bounding_box"]                         # relative xywh
            b = [x * w, y * h, (x + bw) * w, (y + bh) * h]
            if b[2] - b[0] < 2 or b[3] - b[1] < 2:                      # degenerate box
                continue
            boxes.append([round(v, 2) for v in b]); labels.append(CLASSES.index(det["label"]) + 1)
        out.append(Item(s["filepath"], w, h, boxes, labels))
    return out


def make_split(items: Sequence[Item], sizes: dict[str, int] = SPLIT_SIZES) -> dict[str, list[Item]]:
    ordered = sorted(items, key=lambda i: hashlib.sha256(Path(i.file).name.encode()).hexdigest())
    out, start = {}, 0
    for name in ("train", "val", "test"):
        out[name] = ordered[start:start + sizes[name]]; start += sizes[name]
    return out


def split_summary(split: dict[str, list[Item]]) -> dict:
    s = {}
    for name, items in split.items():
        counts = {c: 0 for c in CLASSES}
        for it in items:
            for l in it.labels:
                counts[CLASSES[l - 1]] += 1
        s[name] = {"images": len(items), "boxes": counts, "images_without_boxes": sum(1 for it in items if not it.labels)}
    return s


def write_manifest(split: dict[str, list[Item]], path: Path = MANIFEST) -> dict:
    files = {name: [i.file for i in items] for name, items in split.items()}
    man = {"dataset": REPO_ID, "declared_license": "cc0-1.0", "classes": CLASSES, "rule": "order by sha256(basename); first 1000 train, next 200 val, next 800 test", "summary": split_summary(split), "files": files,
           "files_sha256": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()}
    path.write_text(json.dumps(man, indent=1) + "\n"); return man


def fetch_images(split: dict[str, list[Item]], workers: int = 8) -> Path:
    """Download only the images the split needs. Returns the local dataset root."""
    from huggingface_hub import snapshot_download
    names = sorted({i.file for items in split.values() for i in items})
    return Path(snapshot_download(REPO_ID, repo_type="dataset", allow_patterns=names, max_workers=workers))


class HardHatDataset:
    """torch-style dataset: (image tensor in [0,1], target dict with boxes and labels)."""
    def __init__(self, items: Sequence[Item], root: Path):
        self.items, self.root = list(items), Path(root)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, i: int):
        import torch
        from PIL import Image
        import numpy as np
        it = self.items[i]
        img = Image.open(self.root / it.file).convert("RGB")
        t = torch.from_numpy(np.asarray(img, dtype="float32") / 255.0).permute(2, 0, 1)
        boxes = torch.tensor(it.boxes, dtype=torch.float32).reshape(-1, 4)
        return t, {"boxes": boxes, "labels": torch.tensor(it.labels, dtype=torch.int64), "image_id": i}
