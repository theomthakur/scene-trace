"""Decode with PyAV using real presentation timestamps and sample by time, not by frame count.

Timestamps are integer milliseconds relative to the first presented frame. Sampling picks the first frame at or after each
sample instant, so variable frame rates and odd time bases do not shift events. Frames are oriented upright and resized so the
longest edge is at most `max_long_edge_px`; the returned scale lets callers relate pixels to the original frame.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
import av, cv2, numpy as np
from .probe import MediaError, VideoInfo


@dataclass
class SampledFrame:
    index: int            # index among decoded frames (presentation order)
    sample_index: int     # index among sampled frames
    t_ms: int             # presentation time relative to the first frame
    image: np.ndarray     # RGB uint8, upright, resized
    fell_back: bool       # True when the frame had no pts and a derived time was used


def _orient(img: np.ndarray, rotation: int) -> np.ndarray:
    # PyAV does not apply the display matrix. `rotation` is the clockwise turn needed to display upright.
    k = {0: 0, 90: 3, 180: 2, 270: 1}[rotation]   # np.rot90 turns counter-clockwise
    return np.ascontiguousarray(np.rot90(img, k)) if k else img


def resize_long_edge(img: np.ndarray, max_edge: int) -> np.ndarray:
    h, w = img.shape[:2]
    scale = min(1.0, max_edge / max(h, w))
    if scale >= 1.0:
        return img
    return cv2.resize(img, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA)


def iter_samples(path: Path | str, info: VideoInfo, sample_fps: float, max_long_edge_px: int, *, max_frames: int | None = None) -> Iterator[SampledFrame]:
    period_ms = 1000.0 / sample_fps
    try:
        container = av.open(str(path))
    except av.error.FFmpegError as e:
        raise MediaError("decode_failed", f"The file could not be opened for decoding: {e}")
    with container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        tb = float(stream.time_base) if stream.time_base else 0.0
        first_pts = None
        next_sample = 0.0
        sample_index = 0
        last_t = -1
        fallback_clock = 0.0
        step = 1000.0 / info.avg_fps if info.avg_fps > 0 else period_ms
        try:
            for index, frame in enumerate(container.decode(stream)):
                fell_back = frame.pts is None or tb == 0.0
                if fell_back:
                    t = fallback_clock; fallback_clock += step
                else:
                    if first_pts is None:
                        first_pts = frame.pts
                    t = (frame.pts - first_pts) * tb * 1000.0
                t_ms = int(round(t))
                if t_ms < last_t:            # never let time run backwards
                    t_ms = last_t
                last_t = t_ms
                if t + 1e-6 < next_sample:
                    continue
                while next_sample <= t + 1e-6:
                    next_sample += period_ms
                img = frame.to_ndarray(format="rgb24")
                img = resize_long_edge(_orient(img, info.rotation), max_long_edge_px)
                yield SampledFrame(index, sample_index, t_ms, img, fell_back)
                sample_index += 1
                if max_frames is not None and sample_index >= max_frames:
                    return
        except av.error.FFmpegError as e:
            raise MediaError("decode_failed", f"Decoding failed mid-stream: {e}")
