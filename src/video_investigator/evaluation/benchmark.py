"""Benchmark evaluation. Three clearly separated lanes: fixtures (no detector), real development footage, real frozen-test footage.

Real-footage metrics here come from the pretrained detector on decoded pixels. Fixture metrics never mix with them.
The test split can be evaluated only once: the runner refuses if its results file exists (like the Preference Lab final test).
"""
from __future__ import annotations
import hashlib, json, platform, subprocess, time
from datetime import datetime, timezone
from pathlib import Path
from ..config import REPO, Settings, load_settings
from ..events.rules import detect_events
from ..media.probe import probe
from ..runner import zones_from_dicts
from ..vision.detector import Detector
from ..vision.pipeline import run_detection
from .fixtures import FRAME, scenarios
from .matching import match, summarize

BENCH = REPO / "fixtures" / "benchmark"
CLIPS = REPO / "var" / "candidates"
EVIDENCE = REPO / "docs" / "evidence"
TEST_RESULT = EVIDENCE / "test-results.json"
NOT_MEASURED = [
    "Detection accuracy (mAP) and tracking metrics (ID switches): no ground-truth boxes or tracks were annotated.",
    "Passage occupancy events on real footage: not annotated.",
    "Retrieval Recall@k: not evaluated beyond functional tests of the query parser (no relevance-labelled query set).",
    "Explanation quality: there is no explanation or VLM component.",
    "Generalisation: two CC0 clips (one outdoor pedestrian scene, one traffic scene) cannot represent warehouses or indoor aisles.",
    "Human review time and usefulness: no user study was done.",
]


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def baseline_settings(s: Settings) -> Settings:
    """Temporal logic removed: no dwell, no persistence, no hysteresis. Stationary needs one sampling period (the config requires > 0)."""
    return load_settings(overrides={**s.model_dump(), "events": {**s.events.model_dump(), "exit_hysteresis_s": 0.0,
                                                                 "zone_entry": {**s.events.zone_entry.model_dump(), "dwell_s": 0.0},
                                                                 "passage": {**s.events.passage.model_dump(), "persistence_s": 0.0},
                                                                 "stationary": {**s.events.stationary.model_dump(), "duration_s": 1.0 / s.processing.sample_fps}}})


def load_manifest() -> dict:
    return json.loads((BENCH / "manifest.json").read_text())


def verify_sources(manifest: dict, split: str) -> list[dict]:
    srcs = [s for s in manifest["sources"] if s["split"] == split]
    for s in srcs:
        p = CLIPS / s["file"]
        if not p.is_file() or hashlib.sha1(p.read_bytes()).hexdigest() != s["sha1"]:
            raise SystemExit(f"Missing or changed clip {s['file']}. Run: python scripts/fetch_demo_media.py")
    return srcs


def _unit_results(src: dict, events: list[dict], hours: float) -> list[dict]:
    out = []
    for u in src["units"]:
        pred = [e for e in events if e["type"] in u["types"] and e["zone_id"] in u["zones"]]
        m = match(pred, u["truth"], 0.5)
        m.update({"unit": u["id"], "hours": hours, "negative": not u["truth"], "n_truth": len(u["truth"]), "n_pred": len(pred), "clip": src["id"],
                  "pred": [{k: p[k] for k in ("type", "zone_id", "start_ms", "end_ms", "track_ids", "uncertainty_flags")} for p in pred], "truth": u["truth"]})
        out.append(m)
    return out


def real_lane(manifest: dict, split: str, settings: Settings, detector: Detector, *, with_baseline=True) -> dict:
    srcs = verify_sources(manifest, split)
    base = baseline_settings(settings)
    per, per_b, run_info = [], [], []
    for s in srcs:
        v = CLIPS / s["file"]; info = probe(v)
        zones = zones_from_dicts(json.loads((BENCH / s["zones"]).read_text()))
        det = run_detection(v, info, settings, detector)
        start, end = det.sampled_times_ms[0], det.sampled_times_ms[-1]
        ev = [e.to_dict() for e in detect_events(det.observations, zones, settings, det.frame_size, video_start_ms=start, video_end_ms=end, source=det.source)]
        evb = [e.to_dict() for e in detect_events(det.observations, zones, base, det.frame_size, video_start_ms=start, video_end_ms=end, source=det.source)]
        hours = info.duration_ms / 3.6e6
        per += _unit_results(s, ev, hours); per_b += _unit_results(s, evb, hours)
        run_info.append({"clip": s["id"], "sampled_frames": len(det.sampled_times_ms), "tracks": len({o.track_id for o in det.observations}), "detections": len(det.observations),
                         "timings": det.timings, "quality_flags": det.quality_flags, "observations_sha256": hashlib.sha256(json.dumps([[o.t_ms, o.track_id, o.class_name, [round(x, 5) for x in o.box]] for o in det.observations]).encode()).hexdigest()})
    lane = {"status": "evaluated", "scope": f"{len(srcs)} source recording(s): " + ", ".join(s["id"] for s in srcs) + f". {sum(len(u['truth']) for s in srcs for u in s['units'])} annotated events across {sum(len(s['units']) for s in srcs)} evaluation units "
            f"({sum(1 for s in srcs for u in s['units'] if not u['truth'])} negative). Real pixel inference with pretrained COCO weights.",
            "metrics": summarize(per), "per_clip": {"units": per, "runs": run_info}, "notes": []}
    if with_baseline:
        lane["baseline_no_persistence"] = {"metrics": summarize(per_b), "units": per_b}
    return lane


def fixture_lane(settings: Settings) -> dict:
    per, rows = [], []
    for sc in scenarios():
        s = load_settings(overrides={"processing": {"sample_fps": sc.sample_fps}})
        ev = [e.to_dict() for e in detect_events(sc.observations, sc.zones, s, FRAME, video_end_ms=sc.duration_ms, source="fixture")]
        m = match(ev, sc.truth, 0.5); m.update({"unit": sc.name, "hours": sc.duration_ms / 3.6e6, "negative": not sc.truth})
        per.append(m); rows.append({"scenario": sc.name, "purpose": sc.purpose, "predicted": len(ev), "truth": len(sc.truth), "tp": len(m["matches"]), "fp": len(m["false_positives"]), "fn": len(m["missed"])})
    base = baseline_settings(settings)
    per_b = []
    for sc in scenarios():
        s = load_settings(overrides={"processing": {"sample_fps": sc.sample_fps}}); sb = baseline_settings(s)
        ev = [e.to_dict() for e in detect_events(sc.observations, sc.zones, sb, FRAME, video_end_ms=sc.duration_ms, source="fixture")]
        m = match(ev, sc.truth, 0.5); m.update({"hours": sc.duration_ms / 3.6e6, "negative": not sc.truth}); per_b.append(m)
    del base
    return {"status": "evaluated", "scope": f"{len(per)} generated scenarios with deterministic ground truth. Tests the temporal rules WITHOUT a detector; these numbers say nothing about real video.",
            "metrics": summarize(per), "baseline_no_persistence": {"metrics": summarize(per_b)}, "per_clip": rows, "notes": ["Fixture lane only: scripted observations, tagged source=fixture."]}


def sweep(manifest: dict, base: Settings, detector_factory) -> list[dict]:
    """Sampling-rate and detector-threshold sweep on DEVELOPMENT clips only. Descriptive: one clip, so it cannot select a winner."""
    srcs = verify_sources(manifest, "development"); out = []
    for label, over in [("2 fps", {"processing": {"sample_fps": 2.0}, "events": {"max_gap_s": 0.5}}), ("5 fps (default)", {}), ("10 fps", {"processing": {"sample_fps": 10.0}}),
                        ("5 fps, threshold 0.30", {"detector": {"score_threshold": 0.30}}), ("5 fps, threshold 0.70", {"detector": {"score_threshold": 0.70}})]:
        s = load_settings(overrides=over or None); det = detector_factory(s); tracks = dets = evs = 0; tot = 0.0
        for src in srcs:
            v = CLIPS / src["file"]; info = probe(v); zones = zones_from_dicts(json.loads((BENCH / src["zones"]).read_text()))
            d = run_detection(v, info, s, det)
            ev = detect_events(d.observations, zones, s, d.frame_size, video_start_ms=d.sampled_times_ms[0], video_end_ms=d.sampled_times_ms[-1], source=d.source)
            u = _unit_results(src, [e.to_dict() for e in ev], info.duration_ms / 3.6e6)
            tracks += len({o.track_id for o in d.observations}); dets += len(d.observations); evs += len(ev); tot += d.timings["total_s"]
            tp = sum(len(x["matches"]) for x in u); fp = sum(len(x["false_positives"]) for x in u); fn = sum(len(x["missed"]) for x in u)
        out.append({"label": label, "tracks": tracks, "detections": dets, "events": evs, "total_s": round(tot, 1), "tp": tp, "fp": fp, "fn": fn})
    return out


def git_commit() -> str:
    try:
        return subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    except Exception:
        return "unknown"


def run_evaluation(include_test: bool, with_sweep: bool = True) -> dict:
    settings = load_settings(); manifest = load_manifest()
    detector = Detector(settings)
    t0 = time.time()
    lanes = {"fixture": fixture_lane(settings), "development": real_lane(manifest, "development", settings, detector)}
    if include_test:
        if TEST_RESULT.exists():
            raise SystemExit(f"The frozen test split was already evaluated ({TEST_RESULT}). It must not be re-run or tuned against.")
        lanes["test"] = real_lane(manifest, "test", settings, detector)
    else:
        lanes["test"] = {"status": "not_evaluated", "reason": "The frozen test split has not been run yet. It is run once with --include-test after the configuration is frozen."}
    sw = sweep(manifest, settings, lambda s: Detector(s)) if with_sweep else None
    manifest_sha = hashlib.sha256((BENCH / "manifest.json").read_bytes()).hexdigest()
    rep = {"headline": "Measured on 2 CC0 source recordings plus generated fixtures. Descriptive only: far too small for statistical claims.",
           "generated_at": datetime.now(timezone.utc).isoformat(), "config_hash": settings.config_hash(), "manifest_sha256": manifest_sha, "code_commit": git_commit(),
           "detector": detector.info(), "hardware": f"{platform.machine()} {platform.platform()}, device {detector.device}",
           "annotation": {"method": manifest["annotation"]["method"], "reviewers": manifest["annotation"]["reviewers"], "caveat": manifest["annotation"]["reviewer_note"]},
           "scope_warning": "Two sources (goal was 12). One reviewer annotated from raw frames after seeing detector output on both clips while developing, so even the test split is not blind. "
                            "Fixture-lane scores are about the temporal rules only. Every real-footage figure rests on 1 to 3 events; read the denominators, not the percentages.",
           "lanes": lanes, "sweep": sw, "sweep_note": "Development clip only (one source). It describes how counts move with sampling and threshold; it cannot establish an optimum, and defaults were not changed on this basis." if sw else None,
           "not_measured": NOT_MEASURED, "elapsed_s": round(time.time() - t0, 1)}
    return rep
