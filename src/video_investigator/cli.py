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


def cmd_process(args) -> int:
    from .config import load_settings
    settings = load_settings(args.config, overrides=None)
    zones = load_zones(args.zones) if args.zones else []
    out_root = Path(args.out)
    last = {"n": 0}

    def progress(n, total):
        if n - last["n"] >= 10 or n == total:
            last["n"] = n; print(f"  sampled frames {n}/{total}", file=sys.stderr, flush=True)

    from .runner import process_video
    res = process_video(Path(args.video), zones, settings, out_root, on_progress=lambda n, total, _t: progress(n, total), max_frames=args.max_frames)
    print(json.dumps({"attempt_dir": str(res["attempt_dir"]), **res["summary"]}, indent=2))
    return 0


def cmd_evaluate(args) -> int:
    from .evaluation import benchmark as b
    from .paths import evaluations_dir
    rep = b.run_evaluation(include_test=args.include_test, with_sweep=not args.no_sweep)
    name = "frozen-test" if args.include_test else "development"
    out = evaluations_dir() / f"{name}.json"
    out.write_text(json.dumps(rep, indent=2, sort_keys=True) + "\n")
    b.EVIDENCE.mkdir(parents=True, exist_ok=True)
    (b.EVIDENCE / f"evaluation-{name}.json").write_text(json.dumps(rep, indent=2, sort_keys=True) + "\n")
    if args.include_test:
        (b.EVIDENCE / "test-results.json").write_text(json.dumps({"lane": rep["lanes"]["test"], "config_hash": rep["config_hash"], "generated_at": rep["generated_at"]}, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"written": str(out), "lanes": {k: (v.get("metrics") or v.get("status")) for k, v in rep["lanes"].items()}}, indent=2, default=str)[:3000])
    return 0


def cmd_export_demo(args) -> int:
    """Copy one completed run (observations, events, evidence, playable video) into web/public/demo for the static demo mode."""
    import shutil
    from sqlalchemy import select
    from .api import app as api_app
    from .db import models as m
    from .db.session import make_engine, session_factory, session_scope
    from .paths import data_dir, evaluations_dir
    eng = make_engine(); F = session_factory(eng); out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    with session_scope(F) as s:
        run = s.get(m.Run, args.run_id) if args.run_id else s.scalars(select(m.Run).where(m.Run.state == "completed").order_by(m.Run.created_at.desc())).first()
        if run is None or run.state != "completed":
            raise SystemExit("No completed run to export. Process a video first.")
        v = s.get(m.Video, run.video_id)
        attempt = (data_dir() / run.manifest_rel).parent
        events = [e for e in s.scalars(select(m.Event).where(m.Event.run_id == run.id, m.Event.attempt == run.attempt))]
        ev_out = [{"id": e.id, "event_key": e.event_key, "evidence_base": f"/demo/evidence/{e.event_key}/", "run_id": e.run_id, "type": e.type, "zone_id": e.zone_id, "start_ms": e.start_ms, "end_ms": e.end_ms,
                   "track_ids": e.track_ids, "class_name": e.class_name, "rule_version": e.rule_version, "details": e.details, "uncertainty_flags": e.uncertainty_flags, "evidence": e.evidence,
                   "description": e.description, "group_id": e.group_id, "source": e.source, "review_status": e.review_status, "review_note": e.review_note, "review_version": e.review_version,
                   "reviewed_at": None} for e in events]
        obs = [json.loads(l) for l in (attempt / "observations.jsonl").read_text().splitlines()]
        video = {"id": v.id, "display_name": v.display_name, "source_sha256": v.source_sha256, "size_bytes": v.size_bytes, "duration_ms": v.duration_ms, "width": v.width, "height": v.height,
                 "codec": v.meta.get("codec"), "fps": v.meta.get("avg_fps"), "rotation": v.meta.get("rotation"), "timestamps_ok": True, "ready": True, "derivative_status": "ready",
                 "derivative_error": None, "media_url": "/demo/video.mp4", "created_at": v.created_at.isoformat() + "Z"}
        run_d = {"id": run.id, "video_id": run.video_id, "zone_version": run.zone_version, "state": "completed", "attempt": run.attempt, "progress": 1.0, "processed_ms": v.duration_ms, "errors": [],
                 "quality_flags": run.quality_flags or [], "cancel_requested": False, "complete": True, "config_hash": run.config_hash, "pipeline_version": run.pipeline_version, "detector": run.detector,
                 "timings": run.timings, "manifest_sha256": run.manifest_sha256, "zones": run.zones, "created_at": run.created_at.isoformat() + "Z", "finished_at": None, "data_source": "detector", "retry_count": 0}
        shutil.copy(data_dir() / v.derivative_rel, out / "video.mp4")
        ev_dir = out / "evidence"; ev_dir.mkdir(exist_ok=True)
        for e in events:
            src = attempt / "evidence" / e.event_key
            if src.is_dir():
                shutil.copytree(src, ev_dir / e.event_key, dirs_exist_ok=True)
        evals = {p.stem: json.loads(p.read_text()) for p in evaluations_dir().glob("*.json")}
        index = {"name": v.display_name, "video": video, "run": run_d, "zones": run.zones, "events": ev_out, "observations": obs, "evaluations": evals,
                 "generated_at": datetime.now(timezone.utc).isoformat() if (datetime := __import__("datetime").datetime) else "", "note": "Precomputed static demo. No model runs in this mode."}
    (out / "index.json").write_text(json.dumps(index))
    print(f"exported run {run.id} ({len(ev_out)} events, {len(obs)} observations) to {out}")
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
    e = sub.add_parser("evaluate", help="run the benchmark: fixtures, development footage and (once, with --include-test) the frozen test split")
    e.add_argument("--include-test", action="store_true"); e.add_argument("--no-sweep", action="store_true"); e.set_defaults(fn=cmd_evaluate)
    x = sub.add_parser("export-demo", help="export a completed run for the static demo mode")
    x.add_argument("--run-id"); x.add_argument("--out", default="web/public/demo"); x.set_defaults(fn=cmd_export_demo)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
