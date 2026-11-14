"""Verify a published attempt directory: manifest hashes, event/observation agreement and evidence frames. Returns a list of problems (empty = consistent)."""
from __future__ import annotations
import json, subprocess
from pathlib import Path
from PIL import Image
from .artifacts import is_complete, load_manifest, sha256_bytes


def verify_attempt(attempt: Path) -> list[str]:
    problems: list[str] = []
    if not is_complete(attempt):
        return ["no manifest: the attempt is incomplete"]
    man = load_manifest(attempt)
    for rel, digest in man["files"].items():
        p = attempt / rel
        if not p.is_file():
            problems.append(f"missing file {rel}")
        elif sha256_bytes(p.read_bytes()) != digest:
            problems.append(f"hash mismatch {rel}")
    run = json.loads((attempt / "run.json").read_text()); events = json.loads((attempt / "events.json").read_text())
    obs = [json.loads(l) for l in (attempt / "observations.jsonl").read_text().splitlines()]
    times_by_track: dict[int, set[int]] = {}
    for o in obs:
        x1, y1, x2, y2 = o["box"]
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
            problems.append(f"box outside the normalized frame at {o['t_ms']} ms track {o['track_id']}")
        times_by_track.setdefault(o["track_id"], set()).add(o["t_ms"])
    dur = run["video"]["duration_ms"]
    for e in events:
        tag = f"event {e['event_id']}"
        if not (0 <= e["start_ms"] <= e["end_ms"] <= dur + 1000):
            problems.append(f"{tag}: interval outside the video")
        for tid in e["track_ids"]:
            ts = times_by_track.get(tid, set())
            if e["start_ms"] not in ts or e["end_ms"] not in ts:
                problems.append(f"{tag}: start or end is not an observation time of track {tid}")
        ev = e.get("evidence", {})
        for f in ev.get("frames", []):
            if f.get("missing"):
                continue
            if not any(f["t_ms"] in times_by_track.get(t, set()) for t in e["track_ids"]):
                problems.append(f"{tag}: evidence frame {f['role']} at {f['t_ms']} ms has no matching observation")
            ov, og = Image.open(attempt / f["overlay"]), Image.open(attempt / f["original"])
            if ov.size != og.size or ov.size != (run["video"]["width"], run["video"]["height"]):
                problems.append(f"{tag}: overlay/original size {ov.size}/{og.size} differs from the video {run['video']['width']}x{run['video']['height']}")
        if ev.get("clip"):
            r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(attempt / ev["clip"])], capture_output=True, text=True)
            lo, hi = ev["clip_range_ms"]
            try:
                d = float(r.stdout.strip()) * 1000
                if abs(d - (hi - lo)) > 400:
                    problems.append(f"{tag}: clip is {d:.0f} ms but the evidence range is {hi - lo} ms")
            except ValueError:
                problems.append(f"{tag}: clip unreadable")
    return problems
