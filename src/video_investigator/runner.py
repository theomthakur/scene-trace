"""One processing attempt: probe, validate, detect, track, apply rules, build evidence, publish the manifest atomically."""
from __future__ import annotations
import uuid
from pathlib import Path
from typing import Callable
from . import PIPELINE_VERSION
from .config import Settings
from .events.rules import RULE_VERSION, Zone, detect_events
from .media.probe import probe, sha256_file, validate_limits
from .reports import artifacts
from .reports.evidence import build_event_evidence
from .vision.pipeline import run_detection


def zones_from_dicts(zs: list[dict]) -> list[Zone]:
    return [Zone(z["id"], z.get("name", z["id"]), z["role"], [tuple(p) for p in z["polygon"]]) for z in zs]


def process_video(video: Path, zones: list[Zone], settings: Settings, out_root: Path, *, run_id: str | None = None, attempt_n: int | None = None,
                  on_progress: Callable[[int, int, int], None] | None = None, should_cancel: Callable[[], bool] | None = None,
                  max_frames: int | None = None, make_clips: bool = True, detector=None) -> dict:
    """Returns {attempt_dir, run_id, attempt, summary, observations, events, run_meta, manifest_sha256}."""
    import hashlib
    info = probe(video)
    validate_limits(info, max_bytes=settings.limits.upload_max_bytes, max_seconds=settings.limits.upload_max_seconds)
    run_id = run_id or str(uuid.uuid4())
    run_dir = out_root / run_id
    if attempt_n is None:
        attempt = artifacts.next_attempt_dir(run_dir)
    else:
        attempt = run_dir / f"attempt-{attempt_n}"; run_dir.mkdir(parents=True, exist_ok=True); attempt.mkdir(exist_ok=False)
    det = run_detection(video, info, settings, detector, on_progress=on_progress,
                        should_cancel=should_cancel, max_frames=max_frames)
    start_ms = det.sampled_times_ms[0] if det.sampled_times_ms else 0
    end_ms = det.sampled_times_ms[-1] if det.sampled_times_ms else 0
    events = detect_events(det.observations, zones, settings, det.frame_size, video_start_ms=start_ms, video_end_ms=end_ms, source=det.source)
    obs_rows = [{"t_ms": o.t_ms, "track_id": o.track_id, "class_id": o.class_id, "class_name": o.class_name, "confidence": round(o.confidence, 4),
                 "box": [round(x, 5) for x in o.box], "coordinate_space": "normalized_xyxy_upright", "track_state": o.track_state, "source": det.source}
                for o in det.observations]
    zone_dicts = [{"id": z.id, "name": z.name, "role": z.role, "polygon": [list(p) for p in z.polygon]} for z in zones]
    ev_dicts = [e.to_dict() for e in events]
    refs = build_event_evidence(video, info, attempt, ev_dicts, obs_rows, zone_dicts, int(settings.events.evidence_padding_s * 1000), info.duration_ms, make_clips=make_clips)
    for e in ev_dicts:
        e["evidence"] = refs[e["event_id"]]
    video_sha = sha256_file(video)
    run_meta = {"run_id": run_id, "attempt": attempt.name, "pipeline_version": PIPELINE_VERSION, "config": settings.model_dump(), "config_hash": settings.config_hash(),
                "video": {"file_name": video.name, "sha256": video_sha, **info.to_dict()}, "detector": det.detector_info, "tracker": "custom-iou-hungarian-baseline",
                "rule_version": RULE_VERSION, "processed_frame_size": list(det.frame_size), "timings": det.timings, "quality_flags": det.quality_flags,
                "zones": zone_dicts, "sampled_frames": len(det.sampled_times_ms), "data_source": "detector (real pretrained weights on decoded pixels)" if det.source == "detector" else "FIXTURE (scripted detections; not real inference)"}
    files = {"observations.jsonl": artifacts.write_jsonl(attempt / "observations.jsonl", obs_rows),
             "events.json": artifacts.write_json(attempt / "events.json", ev_dicts),
             "run.json": artifacts.write_json(attempt / "run.json", run_meta)}
    if (attempt / "evidence").exists():
        for p in sorted((attempt / "evidence").rglob("*")):
            if p.is_file():
                files[str(p.relative_to(attempt))] = sha256_file(p)
    mpath = artifacts.publish_manifest(attempt, files, {"video_sha256": video_sha, "config_hash": settings.config_hash(), "status": "completed", "run_id": run_id})
    summary = {"observations": len(obs_rows), "events": len(ev_dicts), "tracks": len({o["track_id"] for o in obs_rows}), **det.timings, "quality_flags": det.quality_flags}
    return {"attempt_dir": attempt, "run_id": run_id, "attempt": attempt.name, "summary": summary, "observations": obs_rows, "events": ev_dicts, "run_meta": run_meta,
            "manifest_sha256": hashlib.sha256(mpath.read_bytes()).hexdigest()}
