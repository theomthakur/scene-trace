"""Evidence frames and clips. Frames come from re-decoding the ORIGINAL video; overlays are drawn from normalized coordinates."""
from __future__ import annotations
import subprocess
from pathlib import Path
import av, cv2, numpy as np
from ..media.decode import _orient
from ..media.probe import VideoInfo

PALETTE = [(37, 99, 235), (217, 119, 6), (5, 150, 105), (190, 24, 93), (109, 40, 217), (8, 145, 178)]


def frame_at(path: Path | str, info: VideoInfo, t_ms: int, tolerance_ms: int = 250):
    """Return (upright RGB frame at original resolution, actual t_ms) for the frame closest to t_ms, or None if none within tolerance."""
    with av.open(str(path)) as c:
        s = c.streams.video[0]; tb = float(s.time_base); first = None; best = None
        for fr in c.decode(s):
            if fr.pts is None:
                continue
            if first is None:
                first = fr.pts
            t = (fr.pts - first) * tb * 1000.0
            if best is None or abs(t - t_ms) < abs(best[0] - t_ms):
                best = (t, fr.to_ndarray(format="rgb24"))
            if t > t_ms + tolerance_ms:
                break
    if best is None or abs(best[0] - t_ms) > tolerance_ms:
        return None
    return _orient(best[1], info.rotation), int(round(best[0]))


def draw_overlay(img: np.ndarray, boxes: list[dict], zones: list[dict] | None = None, highlight: set[int] | None = None) -> np.ndarray:
    out = img.copy(); h, w = out.shape[:2]
    for z in zones or []:
        pts = np.array([[int(x * w), int(y * h)] for x, y in z["polygon"]], np.int32)
        layer = out.copy(); cv2.fillPoly(layer, [pts], (37, 99, 235) if z["role"] == "restricted" else (217, 119, 6))
        out = cv2.addWeighted(layer, 0.18, out, 0.82, 0); cv2.polylines(out, [pts], True, (255, 255, 255), max(2, w // 640))
    for b in boxes:
        x1, y1, x2, y2 = b["box"]; p1, p2 = (int(x1 * w), int(y1 * h)), (int(x2 * w), int(y2 * h))
        col = PALETTE[b["track_id"] % len(PALETTE)]; th = max(2, w // 480) + (2 if highlight and b["track_id"] in highlight else 0)
        cv2.rectangle(out, p1, p2, col, th)
        label = f'{b["class_name"]} #{b["track_id"]} {b["confidence"]:.2f}'
        fs = max(0.5, w / 1600); (tw, tht), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, fs, 1)
        cv2.rectangle(out, (p1[0], max(0, p1[1] - tht - 6)), (p1[0] + tw + 4, p1[1]), col, -1)
        cv2.putText(out, label, (p1[0] + 2, max(tht, p1[1] - 4)), cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255), 1, cv2.LINE_AA)
    return out


def save_jpeg(img_rgb: np.ndarray, path: Path, quality: int = 88) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, quality])


def extract_clip(src: Path | str, dst: Path, start_ms: int, end_ms: int) -> None:
    """Re-encode a padded interval to browser-playable H.264 (no audio). Raises RuntimeError with ffmpeg's message on failure."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    start_s, dur_s = max(0, start_ms) / 1000.0, max(0.1, (end_ms - start_ms) / 1000.0)
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start_s:.3f}", "-i", str(src), "-t", f"{dur_s:.3f}", "-an", "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("clip extraction failed: " + r.stderr.strip()[-300:])


def make_playable_derivative(src: Path | str, dst: Path, max_long_edge: int = 1280) -> None:
    """Browser-playable H.264 MP4 derivative (autorotated by ffmpeg, so normalized boxes stay valid). The original is never modified."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    vf = f"scale='if(gt(iw,ih),min({max_long_edge},iw),-2)':'if(gt(iw,ih),-2,min({max_long_edge},ih))',format=yuv420p"
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-an", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
                        "-movflags", "+faststart", str(dst)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("derivative failed: " + r.stderr.strip()[-300:])
