"""Run the full pipeline on every available clip and record what happens: codec, resolution, frame rate, timing, frames processed, quality flags, and structural checks
(timestamps start at 0 and never go backwards, last sample near the duration, boxes valid, published attempt consistent). Looks for failures, not for accuracy.
   python scripts/robustness_sweep.py   ->  docs/evidence/robustness-sweep.json"""
import json, sys, tempfile, time, traceback
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "src"))
from video_investigator.config import load_settings
from video_investigator.media.probe import probe
from video_investigator.reports.verify import verify_attempt
from video_investigator.runner import process_video

def main():
    s = load_settings(); clips = sorted(list((ROOT / "var/candidates").glob("*.webm")) + list((ROOT / "var/candidates/new").glob("*.webm")) + list((ROOT / "var/candidates/new").glob("*.ogv")) + list((ROOT / "var/candidates/new").glob("*.ogg")))
    out = []; tmp = Path(tempfile.mkdtemp(prefix="vi-sweep-"))
    for c in clips:
        rec = {"file": c.name[:60]}
        try:
            info = probe(c); rec.update(codec=info.codec, size=f"{info.width}x{info.height}", fps=info.avg_fps, duration_s=round(info.duration_ms / 1000, 1), rotation=info.rotation, timestamps_ok=info.timestamps_ok)
            t0 = time.time(); r = process_video(c, [], s, tmp, make_clips=False); dt = time.time() - t0
            ts = sorted({o["t_ms"] for o in r["observations"]}); allts = r["run_meta"]["sampled_frames"]
            problems = verify_attempt(r["attempt_dir"])
            rec.update(ok=True, seconds=round(dt, 1), realtime_factor=round(info.duration_ms / 1000 / dt, 2), sampled_frames=allts, detections=len(r["observations"]), tracks=r["summary"]["tracks"],
                       quality_flags=r["summary"]["quality_flags"], verify_problems=problems, first_obs_ms=ts[0] if ts else None, last_obs_ms=ts[-1] if ts else None,
                       expected_frames=int(info.duration_ms / 1000 * s.processing.sample_fps))
        except Exception as e:
            rec.update(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}")
        out.append(rec); print(json.dumps(rec), flush=True)
    (ROOT / "docs/evidence/robustness-sweep.json").write_text(json.dumps({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "clips": out}, indent=1) + "\n")

if __name__ == "__main__":
    main()
