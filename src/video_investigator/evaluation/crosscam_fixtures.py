"""Synthetic multi-camera scenarios with known identities. SYNTHETIC: descriptors are random vectors plus noise, not images. They test the association logic and show how
metrics degrade as appearance becomes less distinctive. They say nothing about real people or real cameras."""
from __future__ import annotations
import numpy as np
from ..crosscam.associate import Tracklet

DIM = 64


def _unit(v):
    return v / np.linalg.norm(v)


def scenario(n_ids: int = 40, noise: float = 0.5, seed: int = 0, p_visible: float = 0.85, same_class: bool = True):
    """Three cameras A, B, C on a shared clock. Each identity passes A, then B (plausible gap), then C, each with probability p_visible. Returns (A, B, C) tracklet lists."""
    rng = np.random.default_rng(seed); base = {f"id{i}": _unit(rng.normal(size=DIM)) for i in range(n_ids)}
    cams = {"A": [], "B": [], "C": []}
    for k, (ident, vec) in enumerate(base.items()):
        t = rng.uniform(0, 400); prev_end = None
        for cam in ("A", "B", "C"):
            dur = rng.uniform(4, 15)
            start = t if prev_end is None else prev_end + rng.uniform(3, 40)
            if rng.random() < p_visible or cam == "A":
                cams[cam].append(Tracklet(cam, 1000 * k + len(cams[cam]), "person" if same_class else ("person" if k % 2 == 0 else "car"), start, start + dur, _unit(vec + noise * rng.normal(size=DIM) / np.sqrt(DIM)), ident))
            prev_end = start + dur
    return cams["A"], cams["B"], cams["C"]
