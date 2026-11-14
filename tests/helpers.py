"""Test helpers. FixtureDetector is a scripted stand-in tagged source='fixture', so its output can never be mistaken for real inference."""
from __future__ import annotations
import subprocess, sys
from fractions import Fraction
from pathlib import Path
import av, numpy as np
from video_investigator.vision.detector import Detection


def make_video(path: Path, seconds: float = 4.0, fps: int = 25, size=(320, 180)) -> Path:
    """A small H.264 clip with a moving square (for decoding, evidence and clip tests; real objects are NOT needed here)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(path), "w") as c:
        s = c.add_stream("libx264", rate=fps); s.width, s.height, s.pix_fmt = size[0], size[1], "yuv420p"
        for k in range(int(seconds * fps)):
            img = np.full((size[1], size[0], 3), 70, np.uint8); x = int((k / (seconds * fps)) * (size[0] - 40))
            img[60:100, x:x + 40] = (220, 200, 40)
            f = av.VideoFrame.from_ndarray(img, format="rgb24")
            for p in s.encode(f):
                c.mux(p)
        for p in s.encode():
            c.mux(p)
    return path


class FixtureDetector:
    """Returns scripted detections for the k-th sampled frame. `script(k) -> list[Detection]`."""
    source = "fixture"

    def __init__(self, script):
        self.script, self.k = script, 0

    def detect(self, image):
        out = self.script(self.k); self.k += 1
        return out

    def info(self):
        return {"name": "fixture-detector", "weights": "none", "weights_sha256": None, "note": "scripted detections; not real inference"}


def person_in_zone_script(first=3, last=18):
    """A person standing at the centre of the frame from sampled frame `first` to `last` (inclusive)."""
    def script(k):
        if first <= k <= last:
            return [Detection(1, "person", 0.93, (0.45, 0.50, 0.55, 0.90))]
        return []
    return script
