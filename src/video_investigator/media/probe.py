"""Probe a video with ffprobe and validate it before any decode. Dimensions are orientation-corrected (display) dimensions."""
from __future__ import annotations
import hashlib, json, subprocess
from dataclasses import dataclass, asdict
from pathlib import Path


class MediaError(Exception):
    """A media problem with a stable machine-readable code, so the API can return an explicit outcome."""
    def __init__(self, code: str, message: str):
        super().__init__(message); self.code = code; self.message = message


@dataclass
class VideoInfo:
    codec: str
    width: int            # display width after rotation
    height: int           # display height after rotation
    coded_width: int
    coded_height: int
    rotation: int         # degrees clockwise needed to display upright: 0, 90, 180, 270
    duration_ms: int
    avg_fps: float
    time_base: str
    start_time_ms: int
    nb_frames: int | None
    size_bytes: int
    timestamps_ok: bool   # False when the stream gives no usable presentation timestamps

    def to_dict(self) -> dict:
        return asdict(self)


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def _rotation(stream: dict) -> int:
    for sd in stream.get("side_data_list", []) or []:
        if "rotation" in sd:
            # ffprobe reports counter-clockwise degrees in the display matrix; convert to the clockwise turn needed to display upright.
            return int(-round(float(sd["rotation"]))) % 360
    tag = (stream.get("tags") or {}).get("rotate")
    return int(tag) % 360 if tag else 0


def probe(path: Path | str) -> VideoInfo:
    path = Path(path)
    if not path.is_file():
        raise MediaError("not_found", "The video file does not exist.")
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                             capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise MediaError("ffprobe_missing", "ffprobe is not installed. Install ffmpeg (for example: brew install ffmpeg).")
    except subprocess.TimeoutExpired:
        raise MediaError("probe_timeout", "Probing the file timed out.")
    if out.returncode != 0:
        raise MediaError("not_a_video", "The file could not be read as media: " + (out.stderr.strip().splitlines() or ["unknown error"])[-1][:200])
    info = json.loads(out.stdout)
    streams = [s for s in info.get("streams", []) if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic", 0) == 0]
    if not streams:
        raise MediaError("no_video_stream", "The file has no video stream.")
    s = streams[0]
    cw, ch = int(s.get("width") or 0), int(s.get("height") or 0)
    if cw <= 0 or ch <= 0:
        raise MediaError("invalid_dimensions", "The video stream reports no frame dimensions.")
    rot = _rotation(s)
    w, h = (ch, cw) if rot in (90, 270) else (cw, ch)
    fmt = info.get("format", {})
    dur = s.get("duration") or fmt.get("duration")
    try:
        duration_ms = int(round(float(dur) * 1000))
    except (TypeError, ValueError):
        duration_ms = 0
    try:
        num, den = (s.get("avg_frame_rate") or "0/1").split("/")
        fps = float(num) / float(den) if float(den) else 0.0
    except ValueError:
        fps = 0.0
    r_num, r_den = (s.get("r_frame_rate") or "0/1").split("/")
    r_fps = float(r_num) / float(r_den) if float(r_den) else 0.0
    # Some containers (WebM) report a 1000 fps "average" because timestamps are in milliseconds. Prefer r_frame_rate then.
    if fps <= 0 or fps > 240:
        fps = r_fps if 0 < r_fps <= 240 else 0.0
    start = s.get("start_time") or fmt.get("start_time") or 0
    nb = s.get("nb_frames")
    return VideoInfo(
        codec=s.get("codec_name", "unknown"), width=w, height=h, coded_width=cw, coded_height=ch, rotation=rot,
        duration_ms=duration_ms, avg_fps=round(fps, 3), time_base=s.get("time_base", ""), start_time_ms=int(round(float(start) * 1000)),
        nb_frames=int(nb) if nb and str(nb).isdigit() else None, size_bytes=int(fmt.get("size") or path.stat().st_size),
        timestamps_ok=bool(s.get("time_base")) and duration_ms > 0)


def validate_limits(info: VideoInfo, *, max_bytes: int, max_seconds: float) -> None:
    if info.size_bytes > max_bytes:
        raise MediaError("too_large", f"The file is {info.size_bytes / 2**20:.0f} MiB; the limit is {max_bytes / 2**20:.0f} MiB.")
    if info.duration_ms <= 0:
        raise MediaError("no_duration", "The video reports no usable duration, so timestamps cannot be trusted.")
    if info.duration_ms > max_seconds * 1000:
        raise MediaError("too_long", f"The video is {info.duration_ms / 1000:.0f} s; the limit is {max_seconds:.0f} s.")
