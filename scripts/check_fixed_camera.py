"""Objective fixed-camera test: phase-correlation shift of the whole frame between frames one second apart. A tripod or wall-mounted camera gives a median shift near
zero; handheld or moving cameras give large, varying shifts. Also reports resolution, fps, duration and rotation.   python scripts/check_fixed_camera.py clip1 clip2 ..."""
import sys
from pathlib import Path
import cv2, numpy as np
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "src"))
from video_investigator.media.decode import iter_samples
from video_investigator.media.probe import probe


def check(path):
    info = probe(path); prev = None; shifts = []
    for fr in iter_samples(path, info, 1.0, 480):
        g = cv2.cvtColor(fr.image, cv2.COLOR_RGB2GRAY).astype("float32")
        if prev is not None:
            (dx, dy), _ = cv2.phaseCorrelate(prev, g); shifts.append(float(np.hypot(dx, dy)))
        prev = g
    s = np.array(shifts) if shifts else np.array([0.0])
    return {"file": Path(path).name, "wh": f"{info.width}x{info.height}", "fps": info.avg_fps, "dur_s": round(info.duration_ms / 1000, 1), "rot": info.rotation, "median_shift_px_480": round(float(np.median(s)), 2), "p90_shift_px_480": round(float(np.percentile(s, 90)), 2), "max": round(float(s.max()), 2)}


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(check(p))
