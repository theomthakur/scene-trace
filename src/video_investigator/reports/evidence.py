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


def frames_at(path: Path | str, info: VideoInfo, times_ms: list[int], tolerance_ms: int = 250) -> dict[int, tuple[np.ndarray, int]]:
    """One decode pass returning {requested_t_ms: (upright original-resolution RGB frame, actual_t_ms)}. Times with no frame within tolerance are omitted."""
    want = sorted(set(times_ms))
    best: dict[int, tuple[float, np.ndarray | None]] = {w: (1e18, None) for w in want}
    with av.open(str(path)) as c:
        s = c.streams.video[0]; tb = float(s.time_base); first = None
        for fr in c.decode(s):
            if fr.pts is None:
                continue
            if first is None:
                first = fr.pts
            t = (fr.pts - first) * tb * 1000.0
            for w in want:
                if abs(t - w) < abs(best[w][0] - w) and abs(t - w) <= tolerance_ms:
                    best[w] = (t, fr.to_ndarray(format="rgb24"))
            if want and t > want[-1] + tolerance_ms:
                break
    return {w: (_orient(img, info.rotation), int(round(t))) for w, (t, img) in best.items() if img is not None}


def build_event_evidence(video: Path | str, info: VideoInfo, attempt_dir: Path, events: list[dict], observations: list[dict], zones: list[dict],
                         padding_ms: int, duration_ms: int, *, make_clips: bool = True) -> dict[str, dict]:
    """Write evidence/<event_id>/{start,mid,end}.jpg (overlay), *_original.jpg and clip.mp4. Returns {event_id: references}.

    Overlays come from normalized coordinates drawn on the ORIGINAL-resolution frame. Frame times are snapped to observation times of
    the event's own track, so a drawn box always corresponds to a stored observation.
    """
    by_t: dict[int, list[dict]] = {}
    for o in observations:
        by_t.setdefault(o["t_ms"], []).append(o)
    plan: dict[str, list[tuple[str, int]]] = {}
    for e in events:
        tr_times = sorted({o["t_ms"] for o in observations if o["track_id"] in e["track_ids"] and e["start_ms"] <= o["t_ms"] <= e["end_ms"]}) or [e["start_ms"], e["end_ms"]]
        mid = min(tr_times, key=lambda x: abs(x - (e["start_ms"] + e["end_ms"]) / 2))
        plan[e["event_id"]] = [("start", e["start_ms"]), ("mid", mid), ("end", e["end_ms"])]
    wanted = [t for roles in plan.values() for _, t in roles]
    got = frames_at(video, info, wanted)
    refs: dict[str, dict] = {}
    for e in events:
        d = attempt_dir / "evidence" / e["event_id"]
        frames = []
        for role, t in plan[e["event_id"]]:
            if t not in got:
                frames.append({"role": role, "t_ms": t, "missing": True}); continue
            img, actual = got[t]
            boxes = [o for o in by_t.get(t, []) if o["track_state"] == "confirmed"]
            save_jpeg(draw_overlay(img, boxes, zones, highlight=set(e["track_ids"])), d / f"{role}.jpg")
            save_jpeg(img, d / f"{role}_original.jpg")
            frames.append({"role": role, "t_ms": t, "frame_t_ms": actual, "overlay": f"evidence/{e['event_id']}/{role}.jpg",
                           "original": f"evidence/{e['event_id']}/{role}_original.jpg", "boxes_drawn": len(boxes), "track_ids": [b["track_id"] for b in boxes]})
        ref = {"frames": frames, "clip": None, "clip_range_ms": [max(0, e["start_ms"] - padding_ms), min(duration_ms, e["end_ms"] + padding_ms)]}
        if make_clips:
            try:
                extract_clip(video, d / "clip.mp4", ref["clip_range_ms"][0], ref["clip_range_ms"][1]); ref["clip"] = f"evidence/{e['event_id']}/clip.mp4"
            except RuntimeError as err:
                ref["clip_error"] = str(err)
        refs[e["event_id"]] = ref
    return refs
