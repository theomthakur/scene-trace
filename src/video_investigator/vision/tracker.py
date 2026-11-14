"""Baseline multi-object tracker (custom, not ByteTrack or DeepSORT).

Per-class tracks, constant-velocity prediction over real elapsed time, IoU gating, and Hungarian assignment with
scipy.optimize.linear_sum_assignment. Lifecycle: tentative -> confirmed -> lost -> ended. IDs increase monotonically and are
never recycled within a run. There is no re-identification: a track that ends is not revived if the object reappears.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
from scipy.optimize import linear_sum_assignment

BIG = 1e6


def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Pairwise IoU between (N,4) and (M,4) xyxy arrays. Handles empty inputs."""
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    x1 = np.maximum(a[:, None, 0], b[None, :, 0]); y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2]); y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1]); area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter
    return np.where(union > 0, inter / np.maximum(union, 1e-12), 0.0)


@dataclass
class Track:
    track_id: int
    class_id: int
    class_name: str
    box: np.ndarray              # last observed box, normalized xyxy
    t_ms: int                    # time of last observation
    velocity: np.ndarray = field(default_factory=lambda: np.zeros(4))   # box change per second
    hits: int = 1
    state: str = "tentative"     # tentative | confirmed | lost | ended
    first_t_ms: int = 0

    def predict(self, t_ms: int) -> np.ndarray:
        dt = max(0.0, (t_ms - self.t_ms) / 1000.0)
        pred = self.box + self.velocity * dt
        # keep a valid box
        x1, y1, x2, y2 = pred
        if x2 <= x1: x2 = x1 + 1e-4
        if y2 <= y1: y2 = y1 + 1e-4
        return np.array([x1, y1, x2, y2])


@dataclass
class Observation:
    t_ms: int
    track_id: int
    class_id: int
    class_name: str
    confidence: float            # detector score, NOT a calibrated probability and NOT event correctness
    box: tuple[float, float, float, float]
    track_state: str             # state of the track at this observation


class Tracker:
    def __init__(self, iou_gate: float, max_missing_s: float, min_hits: int, smoothing: float):
        self.iou_gate, self.max_missing_ms = iou_gate, max_missing_s * 1000.0
        self.min_hits, self.alpha = min_hits, smoothing
        self.tracks: list[Track] = []
        self._next_id = 1
        self.ended: list[Track] = []

    def update(self, t_ms: int, detections) -> list[Observation]:
        """Associate this frame's detections with live tracks and return one Observation per detection."""
        for tr in self.tracks:                                # a track missing longer than its lifetime ends BEFORE matching: no revival
            if tr.state != "ended" and t_ms - tr.t_ms > self.max_missing_ms:
                tr.state = "ended"; self.ended.append(tr)
        self.tracks = [tr for tr in self.tracks if tr.state != "ended"]
        live = list(self.tracks)
        det_boxes = np.array([d.box for d in detections], dtype=float).reshape(-1, 4)
        pred = np.array([tr.predict(t_ms) for tr in live], dtype=float).reshape(-1, 4)
        iou = iou_matrix(pred, det_boxes)
        cost = 1.0 - iou
        for i, tr in enumerate(live):                       # class-incompatible pairs are never matched
            for j, d in enumerate(detections):
                if tr.class_id != d.class_id or iou[i, j] < self.iou_gate:
                    cost[i, j] = BIG
        matches: dict[int, int] = {}
        if cost.size:
            rows, cols = linear_sum_assignment(cost)
            for i, j in zip(rows, cols):
                if cost[i, j] < BIG:                         # reject assignments beyond the gate
                    matches[j] = i
        obs: list[Observation] = []
        matched_tracks: set[int] = set()
        for j, d in enumerate(detections):
            if j in matches:
                tr = live[matches[j]]; matched_tracks.add(matches[j])
                dt = max((t_ms - tr.t_ms) / 1000.0, 1e-3)
                inst_v = (np.array(d.box) - tr.box) / dt
                tr.velocity = self.alpha * inst_v + (1 - self.alpha) * tr.velocity
                tr.box, tr.t_ms, tr.hits = np.array(d.box), t_ms, tr.hits + 1
                tr.state = "confirmed" if tr.hits >= self.min_hits else "tentative"
            else:
                tr = Track(self._next_id, d.class_id, d.class_name, np.array(d.box), t_ms, first_t_ms=t_ms)
                tr.state = "confirmed" if self.min_hits <= 1 else "tentative"
                self._next_id += 1; self.tracks.append(tr)
            obs.append(Observation(t_ms, tr.track_id, d.class_id, d.class_name, d.score, tuple(float(x) for x in d.box), tr.state))
        for i, tr in enumerate(live):                        # unmatched live tracks: lost, then ended after the missing lifetime
            if i in matched_tracks:
                continue
            if t_ms - tr.t_ms > self.max_missing_ms:
                tr.state = "ended"; self.ended.append(tr)
            elif tr.state == "confirmed":
                tr.state = "lost"
        self.tracks = [tr for tr in self.tracks if tr.state != "ended"]
        return obs
