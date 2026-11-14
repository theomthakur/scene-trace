"""Decode -> detect -> track. Produces timestamped observations. This module never invents detections."""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from ..config import Settings
from ..media.decode import iter_samples
from ..media.probe import VideoInfo
from .detector import Detector
from .tracker import Observation, Tracker


class Cancelled(Exception):
    pass


@dataclass
class DetectionRun:
    observations: list[Observation]
    sampled_times_ms: list[int]
    frame_size: tuple[int, int]            # processed (w, h)
    timings: dict
    quality_flags: list[str] = field(default_factory=list)
    detector_info: dict = field(default_factory=dict)


def run_detection(path: Path | str, info: VideoInfo, settings: Settings, detector: Detector | None = None, *,
                  on_progress: Callable[[int, int], None] | None = None, should_cancel: Callable[[], bool] | None = None,
                  max_frames: int | None = None) -> DetectionRun:
    detector = detector or Detector(settings)
    p = settings.tracker
    tracker = Tracker(p.iou_gate, p.max_missing_s, p.min_hits_to_confirm, p.velocity_smoothing)
    observations: list[Observation] = []
    times: list[int] = []
    flags: set[str] = set()
    detect_s = 0.0
    t0 = time.perf_counter()
    expected = max(1, int(info.duration_ms / 1000.0 * settings.processing.sample_fps))
    size = (0, 0)
    n_det = 0
    for fr in iter_samples(path, info, settings.processing.sample_fps, settings.processing.max_long_edge_px, max_frames=max_frames):
        if should_cancel and should_cancel():
            raise Cancelled()
        size = (fr.image.shape[1], fr.image.shape[0])
        if fr.fell_back:
            flags.add("timestamp_fallback")
        t1 = time.perf_counter()
        dets = detector.detect(fr.image)
        detect_s += time.perf_counter() - t1
        n_det += len(dets)
        observations.extend(tracker.update(fr.t_ms, dets))
        times.append(fr.t_ms)
        if on_progress:
            on_progress(fr.sample_index + 1, expected)
    if not times:
        flags.add("no_frames_decoded")
    else:
        if n_det / len(times) < settings.quality.sparse_detections_per_frame:
            flags.add("sparse_detections")
        period = 1000.0 / settings.processing.sample_fps
        gaps = [b - a for a, b in zip(times, times[1:])]
        if any(g > period * settings.quality.long_gap_factor for g in gaps):
            flags.add("long_gaps")
    total_s = time.perf_counter() - t0
    timings = {"total_s": round(total_s, 3), "detect_s": round(detect_s, 3), "sampled_frames": len(times), "detections": n_det,
               "detect_ms_per_frame": round(1000 * detect_s / max(1, len(times)), 1),
               "realtime_factor": round((times[-1] - times[0]) / 1000.0 / total_s, 3) if len(times) > 1 and total_s > 0 else None}
    return DetectionRun(observations, times, size, timings, sorted(flags), detector.info())
