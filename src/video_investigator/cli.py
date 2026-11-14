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
