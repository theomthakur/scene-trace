"""Event matching and metrics: same type and zone, temporal IoU >= threshold, one-to-one greedy by IoU.

Undefined ratios are returned as None with a reason, never as perfect scores.
"""
from __future__ import annotations
from typing import Sequence


def tiou(a: tuple[int, int], b: tuple[int, int]) -> float:
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    union = (a[1] - a[0]) + (b[1] - b[0]) - inter
    if union <= 0:
        return 1.0 if a == b else 0.0      # two instantaneous events at the same time
    return inter / union


def match(pred: Sequence[dict], truth: Sequence[dict], iou_threshold: float = 0.5) -> dict:
    cands = []
    for i, p in enumerate(pred):
        for j, t in enumerate(truth):
            if p["type"] == t["type"] and p.get("zone_id") == t.get("zone_id"):
                v = tiou((p["start_ms"], p["end_ms"]), (t["start_ms"], t["end_ms"]))
                if v >= iou_threshold:
                    cands.append((v, i, j))
    cands.sort(key=lambda c: (-c[0], c[1], c[2]))
    used_p, used_t, pairs = set(), set(), []
    for v, i, j in cands:
        if i in used_p or j in used_t:
            continue
        used_p.add(i); used_t.add(j)
        pairs.append({"pred": i, "truth": j, "tiou": round(v, 4), "onset_abs_error_ms": abs(pred[i]["start_ms"] - truth[j]["start_ms"])})
    return {"matches": pairs, "false_positives": [i for i in range(len(pred)) if i not in used_p], "missed": [j for j in range(len(truth)) if j not in used_t]}


def ratio(num: int, den: int, why: str) -> dict:
    return {"value": (num / den) if den else None, "numerator": num, "denominator": den, "undefined_reason": None if den else why}


def summarize(results: Sequence[dict]) -> dict:
    """results: per-clip dicts from match(), plus 'hours' (evaluated video hours) and 'negative' (bool: clip has no truth events)."""
    tp = sum(len(r["matches"]) for r in results)
    fp = sum(len(r["false_positives"]) for r in results)
    fn = sum(len(r["missed"]) for r in results)
    neg_hours = sum(r.get("hours", 0.0) for r in results if r.get("negative"))
    neg_fp = sum(len(r["false_positives"]) for r in results if r.get("negative"))
    errs = [m["onset_abs_error_ms"] for r in results for m in r["matches"]]
    return {"true_positives": tp, "false_positives": fp, "missed_events": fn,
            "precision": ratio(tp, tp + fp, "no predicted events"), "recall": ratio(tp, tp + fn, "no ground-truth events"),
            "false_alerts_per_negative_video_hour": {"value": (neg_fp / neg_hours) if neg_hours > 0 else None, "false_alerts": neg_fp, "negative_hours": round(neg_hours, 5),
                                                     "undefined_reason": None if neg_hours > 0 else "no negative-video time evaluated"},
            "onset_abs_error_ms_mean": (sum(errs) / len(errs)) if errs else None, "onset_matched_count": len(errs)}
