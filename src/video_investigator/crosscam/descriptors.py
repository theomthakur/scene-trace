"""Per-track appearance descriptors from saved observations and the ORIGINAL video: the mean of a few CLIP-style crop embeddings."""
from __future__ import annotations
from collections import defaultdict
from pathlib import Path
from typing import Sequence
import numpy as np
from PIL import Image
from ..media.probe import probe
from ..reports.evidence import frames_at
from .associate import Tracklet


def _crop(img: np.ndarray, box, pad=0.1):
    h, w = img.shape[:2]; x1, y1, x2, y2 = box; bw, bh = (x2 - x1) * w, (y2 - y1) * h
    if bw < 24 or bh < 24:
        return None
    return Image.fromarray(img[max(0, int(y1 * h - bh * pad)):min(h, int(y2 * h + bh * pad)), max(0, int(x1 * w - bw * pad)):min(w, int(x2 * w + bw * pad))])


def pick_times(obs: Sequence[dict], k: int) -> list[dict]:
    """Up to k observations spread evenly over the track, preferring larger boxes at each slot."""
    o = sorted(obs, key=lambda x: x["t_ms"])
    if len(o) <= k:
        return o
    slots = np.array_split(np.arange(len(o)), k)
    return [max((o[i] for i in s), key=lambda x: (x["box"][2] - x["box"][0]) * (x["box"][3] - x["box"][1])) for s in slots]


def track_observations(observations: Sequence[dict], min_obs: int = 3, classes: Sequence[str] | None = None) -> dict[int, list[dict]]:
    by: dict[int, list[dict]] = defaultdict(list)
    for o in observations:
        if o["track_state"] == "confirmed" and (classes is None or o["class_name"] in classes):
            by[o["track_id"]].append(o)
    return {k: v for k, v in by.items() if len(v) >= min_obs}


def embed_track_crops(video: Path, observations: Sequence[dict], embedder, tracks: dict[int, list[dict]], k: int = 5) -> dict[int, list[tuple[int, np.ndarray]]]:
    """{track_id: [(t_ms, embedding), ...]} for the chosen crops of each track, decoding the video once."""
    chosen = {tid: pick_times(v, k) for tid, v in tracks.items()}
    times = sorted({o["t_ms"] for v in chosen.values() for o in v})
    frames = frames_at(video, probe(video), times)
    imgs, index = [], []
    for tid, v in chosen.items():
        for o in v:
            if o["t_ms"] in frames:
                c = _crop(frames[o["t_ms"]][0], o["box"])
                if c is not None:
                    imgs.append(c); index.append((tid, o["t_ms"]))
    emb = embedder.embed_images(imgs) if imgs else np.zeros((0, embedder.dim), "float32")
    out: dict[int, list[tuple[int, np.ndarray]]] = defaultdict(list)
    for (tid, t), e in zip(index, emb):
        out[tid].append((t, e))
    return dict(out)


def mean_descriptor(embs: Sequence[np.ndarray]) -> np.ndarray:
    m = np.mean(np.stack(embs), axis=0); return m / max(np.linalg.norm(m), 1e-12)


def to_tracklets(camera: str, tracks: dict[int, list[dict]], crops: dict[int, list[tuple[int, np.ndarray]]], clock_offset_s: float = 0.0) -> list[Tracklet]:
    out = []
    for tid, v in tracks.items():
        if tid not in crops or not crops[tid]:
            continue
        ts = [o["t_ms"] for o in v]
        out.append(Tracklet(camera, tid, v[0]["class_name"], clock_offset_s + min(ts) / 1000.0, clock_offset_s + max(ts) / 1000.0, mean_descriptor([e for _, e in crops[tid]])))
    return out
