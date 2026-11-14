"""Command line: doctor, process, evaluate, export-demo."""
from __future__ import annotations
import argparse, json, platform, shutil, subprocess, sys, time
from pathlib import Path


def cmd_doctor(args) -> int:
    from .config import load_settings
    import torch, torchvision, av, cv2, scipy, numpy
    report: dict = {"python": platform.python_version(), "platform": platform.platform(), "machine": platform.machine(),
                    "torch": torch.__version__, "torchvision": torchvision.__version__, "pyav": av.__version__, "opencv": cv2.__version__,
                    "scipy": scipy.__version__, "numpy": numpy.__version__,
                    "mps_available": bool(torch.backends.mps.is_available()), "cuda_available": bool(torch.cuda.is_available()),
                    "ffmpeg": shutil.which("ffmpeg"), "ffprobe": shutil.which("ffprobe")}
    ok = True
    if not report["ffmpeg"] or not report["ffprobe"]:
        ok = False; report["ffmpeg_error"] = "ffmpeg/ffprobe missing. Install with: brew install ffmpeg"
    else:
        enc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
        report["h264_encoder"] = "libx264" in enc
        if not report["h264_encoder"]:
            report["h264_note"] = "libx264 missing: browser-playable derivatives cannot be made; install an ffmpeg build with libx264."
    settings = load_settings(args.config)
    report["config_hash"] = settings.config_hash()
    try:
        from .vision.detector import Detector
        t0 = time.perf_counter(); det = Detector(settings); load_s = time.perf_counter() - t0
        report["detector"] = det.info(); report["detector_load_s"] = round(load_s, 2)
        if args.clip:
            from .media.probe import probe
            from .media.decode import iter_samples
            info = probe(args.clip)
            fr = next(iter(iter_samples(args.clip, info, settings.processing.sample_fps, settings.processing.max_long_edge_px)))
            det.detect(fr.image)                                  # warm-up
            t0 = time.perf_counter(); dets = det.detect(fr.image); dt = time.perf_counter() - t0
            report["smoke"] = {"clip": str(args.clip), "frame_t_ms": fr.t_ms, "frame_shape": list(fr.image.shape),
                               "detections": [{"class": d.class_name, "score": round(d.score, 3)} for d in dets], "detect_s": round(dt, 3)}
    except Exception as e:
        ok = False; report["detector_error"] = getattr(e, "message", str(e))
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


def load_zones(path):
    from .events.rules import Zone
    from .events.geometry import validate_polygon
    zones = []
    for z in json.loads(Path(path).read_text()):
        poly = [tuple(p) for p in z["polygon"]]
        err = validate_polygon(poly)
        if err:
            raise SystemExit(f"zone {z.get('id')}: {err}")
        zones.append(Zone(z["id"], z.get("name", z["id"]), z["role"], poly))
    return zones


def process_video(video: Path, zones, settings, out_root: Path, *, run_id: str | None = None, on_progress=None, should_cancel=None, max_frames=None):
    """Run the whole pipeline on one video and publish an attempt directory. Returns (attempt_dir, summary)."""
    import uuid
    from . import PIPELINE_VERSION
    from .events.rules import detect_events
    from .media.probe import probe, validate_limits, sha256_file
    from .reports.artifacts import next_attempt_dir, publish_manifest, write_json, write_jsonl
    from .vision.pipeline import run_detection
    info = probe(video)
    validate_limits(info, max_bytes=settings.limits.upload_max_bytes, max_seconds=settings.limits.upload_max_seconds)
    run_id = run_id or str(uuid.uuid4())
    attempt = next_attempt_dir(out_root / run_id)
    det = run_detection(video, info, settings, on_progress=on_progress, should_cancel=should_cancel, max_frames=max_frames)
    start_ms = det.sampled_times_ms[0] if det.sampled_times_ms else 0
    end_ms = det.sampled_times_ms[-1] if det.sampled_times_ms else 0
    events = detect_events(det.observations, zones, settings, det.frame_size, video_start_ms=start_ms, video_end_ms=end_ms, source="detector")
    obs_rows = [{"t_ms": o.t_ms, "track_id": o.track_id, "class_id": o.class_id, "class_name": o.class_name, "confidence": round(o.confidence, 4),
                 "box": [round(x, 5) for x in o.box], "coordinate_space": "normalized_xyxy_upright", "track_state": o.track_state, "source": "detector"}
                for o in det.observations]
    video_sha = sha256_file(video)
    run_meta = {"run_id": run_id, "attempt": attempt.name, "pipeline_version": PIPELINE_VERSION, "config": settings.model_dump(), "config_hash": settings.config_hash(),
                "video": {"path_name": video.name, "sha256": video_sha, **info.to_dict()}, "detector": det.detector_info, "tracker": "custom-iou-hungarian-baseline",
                "rule_version": "rules-1", "processed_frame_size": list(det.frame_size), "timings": det.timings, "quality_flags": det.quality_flags,
                "zones": [{"id": z.id, "name": z.name, "role": z.role, "polygon": z.polygon} for z in zones], "sampled_frames": len(det.sampled_times_ms)}
    files = {"observations.jsonl": write_jsonl(attempt / "observations.jsonl", obs_rows),
             "events.json": write_json(attempt / "events.json", [e.to_dict() for e in events]),
             "run.json": write_json(attempt / "run.json", run_meta)}
    publish_manifest(attempt, files, {"video_sha256": video_sha, "config_hash": settings.config_hash(), "status": "completed"})
    return attempt, {"observations": len(obs_rows), "events": len(events), "tracks": len({o.track_id for o in det.observations}), **det.timings, "quality_flags": det.quality_flags}


def cmd_process(args) -> int:
    from .config import load_settings
    settings = load_settings(args.config, overrides=None)
    zones = load_zones(args.zones) if args.zones else []
    out_root = Path(args.out)
    last = {"n": 0}

    def progress(n, total):
        if n - last["n"] >= 10 or n == total:
            last["n"] = n; print(f"  sampled frames {n}/{total}", file=sys.stderr, flush=True)

    attempt, summary = process_video(Path(args.video), zones, settings, out_root, on_progress=progress, max_frames=args.max_frames)
    print(json.dumps({"attempt_dir": str(attempt), **summary}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="video_investigator.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("doctor", help="check the environment and run the real detector once")
    d.add_argument("--config"); d.add_argument("--clip", help="optional video for a one-frame inference smoke test")
    d.set_defaults(fn=cmd_doctor)
    p = sub.add_parser("process", help="run the full pipeline on one video")
    p.add_argument("video"); p.add_argument("--zones"); p.add_argument("--out", default="var/runs"); p.add_argument("--config"); p.add_argument("--max-frames", type=int)
    p.set_defaults(fn=cmd_process)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
