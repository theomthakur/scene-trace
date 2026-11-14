"""Real pretrained detector: torchvision Faster R-CNN MobileNetV3-Large 320 FPN with COCO weights.

If the weights cannot be loaded this raises DetectorError. There is deliberately no fallback to random weights or canned
predictions: a missing model must be visible, never silently replaced.
"""
from __future__ import annotations
import hashlib
from dataclasses import dataclass
from pathlib import Path
import torch, torchvision
from torchvision.models.detection import FasterRCNN_MobileNet_V3_Large_320_FPN_Weights, fasterrcnn_mobilenet_v3_large_320_fpn
from ..config import Settings


class DetectorError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message); self.code = code; self.message = message


@dataclass
class Detection:
    class_id: int
    class_name: str
    score: float
    box: tuple[float, float, float, float]   # normalized xyxy in the processed (upright) frame


def pick_device(requested: str) -> str:
    """CPU is the required default. mps/cuda are opt-in and only used if torch reports them available."""
    if requested == "cpu":
        return "cpu"
    if requested == "mps" and torch.backends.mps.is_available():
        return "mps"
    if requested == "cuda" and torch.cuda.is_available():
        return "cuda"
    raise DetectorError("device_unavailable", f"Requested device '{requested}' is not available; use cpu.")


class Detector:
    source = "detector"          # tag carried into observations and events; test doubles use "fixture"

    def __init__(self, settings: Settings):
        cfg = settings.detector
        if cfg.name != "fasterrcnn_mobilenet_v3_large_320_fpn" or cfg.weights != "COCO_V1":
            raise DetectorError("unsupported_detector", "Only fasterrcnn_mobilenet_v3_large_320_fpn with COCO_V1 weights is wired up.")
        self.cfg = cfg
        self.device = pick_device(cfg.device)
        self.weights = FasterRCNN_MobileNet_V3_Large_320_FPN_Weights.COCO_V1
        try:
            model = fasterrcnn_mobilenet_v3_large_320_fpn(weights=self.weights, weights_backbone=None, box_score_thresh=min(0.05, cfg.score_threshold))
        except Exception as e:  # network failure, corrupt download, incompatible state dict
            raise DetectorError("weights_unavailable", f"Could not load the pretrained weights: {e}")
        self.model = model.to(self.device).eval()
        self.categories: list[str] = list(self.weights.meta["categories"])
        unknown = [c for c in cfg.classes if c not in self.categories]
        if unknown:
            raise DetectorError("unknown_class", f"Classes not in the COCO label set: {unknown}")
        self.allowed = {self.categories.index(c) for c in cfg.classes}
        self.threshold = cfg.score_threshold

    def weights_path(self) -> Path:
        return Path(torch.hub.get_dir()) / "checkpoints" / Path(self.weights.url).name

    def info(self) -> dict:
        p = self.weights_path()
        sha = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
        return {"name": self.cfg.name, "weights": "COCO_V1", "weights_url": self.weights.url, "weights_sha256": sha,
                "weights_file": p.name, "torch": torch.__version__, "torchvision": torchvision.__version__, "device": self.device,
                "score_threshold": self.threshold, "supported_classes": list(self.cfg.classes),
                "num_coco_categories": len(self.categories), "box_format": "normalized xyxy"}

    @torch.inference_mode()
    def detect(self, image_rgb) -> list[Detection]:
        h, w = image_rgb.shape[:2]
        t = torch.from_numpy(image_rgb).permute(2, 0, 1).float().div_(255.0).to(self.device)
        out = self.model([t])[0]
        dets: list[Detection] = []
        for box, label, score in zip(out["boxes"].cpu().tolist(), out["labels"].cpu().tolist(), out["scores"].cpu().tolist()):
            if score < self.threshold or label not in self.allowed:
                continue
            x1, y1, x2, y2 = box
            nb = (max(0.0, min(1.0, x1 / w)), max(0.0, min(1.0, y1 / h)), max(0.0, min(1.0, x2 / w)), max(0.0, min(1.0, y2 / h)))
            if nb[2] <= nb[0] or nb[3] <= nb[1]:
                continue
            dets.append(Detection(label, self.categories[label], float(score), nb))
        return dets
