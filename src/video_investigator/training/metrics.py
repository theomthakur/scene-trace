"""Detection average precision at an IoU threshold (all-point interpolation, VOC style) and an image-level bootstrap. Pure numpy; tested on small cases."""
from __future__ import annotations
from typing import Sequence
import numpy as np


def iou_one_to_many(box: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    if len(boxes) == 0:
        return np.zeros(0)
    x1 = np.maximum(box[0], boxes[:, 0]); y1 = np.maximum(box[1], boxes[:, 1]); x2 = np.minimum(box[2], boxes[:, 2]); y2 = np.minimum(box[3], boxes[:, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    a = (box[2] - box[0]) * (box[3] - box[1]); b = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    return inter / np.maximum(a + b - inter, 1e-12)


def average_precision(preds: Sequence[tuple[np.ndarray, np.ndarray]], gts: Sequence[np.ndarray], iou_thr: float = 0.5) -> dict:
    """preds[i] = (boxes Nx4, scores N) for image i; gts[i] = boxes Mx4. Each ground-truth box can be matched once; extra detections are false positives.
    Returns {"ap": float|None, "n_gt", "n_pred"}; ap is None (undefined, not zero) when there is no ground truth."""
    n_gt = int(sum(len(g) for g in gts)); dets = []
    for i, (b, s) in enumerate(preds):
        for k in range(len(s)):
            dets.append((float(s[k]), i, np.asarray(b[k], float)))
    dets.sort(key=lambda d: -d[0])
    if n_gt == 0:
        return {"ap": None, "n_gt": 0, "n_pred": len(dets)}
    used = [np.zeros(len(g), bool) for g in gts]; tp = np.zeros(len(dets)); fp = np.zeros(len(dets))
    for j, (_, i, box) in enumerate(dets):
        ious = iou_one_to_many(box, np.asarray(gts[i], float).reshape(-1, 4))
        k = int(np.argmax(ious)) if len(ious) else -1
        if k >= 0 and ious[k] >= iou_thr and not used[i][k]:
            used[i][k] = True; tp[j] = 1
        else:
            fp[j] = 1
    ctp, cfp = np.cumsum(tp), np.cumsum(fp)
    rec = ctp / n_gt; prec = ctp / np.maximum(ctp + cfp, 1e-12)
    mrec = np.concatenate([[0.0], rec, [1.0]]); mpre = np.concatenate([[0.0], prec, [0.0]])
    for k in range(len(mpre) - 2, -1, -1):
        mpre[k] = max(mpre[k], mpre[k + 1])
    idx = np.where(mrec[1:] != mrec[:-1])[0]
    return {"ap": float(np.sum((mrec[idx + 1] - mrec[idx]) * mpre[idx + 1])), "n_gt": n_gt, "n_pred": len(dets)}


def bootstrap_difference(a_preds, b_preds, gts, iou_thr=0.5, n_boot=500, seed=7) -> dict:
    """95% percentile interval of AP(a) - AP(b) over resamples of IMAGES (the test sampling unit), the same resample applied to both models."""
    rng = np.random.default_rng(seed); n = len(gts); diffs = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        ga = [gts[i] for i in idx]
        ra = average_precision([a_preds[i] for i in idx], ga, iou_thr)["ap"]; rb = average_precision([b_preds[i] for i in idx], ga, iou_thr)["ap"]
        if ra is not None and rb is not None:
            diffs.append(ra - rb)
    if not diffs:
        return {"low": None, "high": None, "resamples": 0}
    return {"low": float(np.percentile(diffs, 2.5)), "high": float(np.percentile(diffs, 97.5)), "resamples": len(diffs)}
