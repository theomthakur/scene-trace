"""Execute one claimed run: heartbeat in a thread, cancel checks between frames, publish artifacts BEFORE the database says completed."""
from __future__ import annotations
import errno, threading
from pathlib import Path
from typing import Callable
from sqlalchemy import insert, update
from ..config import Settings
from ..db import models as m
from ..db.session import session_scope, with_lock_retry
from ..media.probe import MediaError
from ..paths import data_dir, runs_dir
from ..runner import process_video, zones_from_dicts
from ..vision.detector import DetectorError
from ..vision.pipeline import Cancelled
from . import store


class Stopped(Exception):
    """The worker process was asked to stop (SIGTERM). The run is marked interrupted, not cancelled."""


Pipeline = Callable[..., dict]


def _fail(factory, run_id: str, code: str, message: str, retryable: bool, *, state="failed", requeue=False):
    def go():
        with session_scope(factory) as s:
            run = s.get(m.Run, run_id)
            run.errors = [*(run.errors or []), {"code": code, "message": message, "retryable": retryable}]
            run.lease_owner, run.finished_at = None, store.utcnow().replace(tzinfo=None)
            if requeue:
                run.state, run.retry_count, run.finished_at = "queued", (run.retry_count or 0) + 1, None
            else:
                run.state = state
    with_lock_retry(go)


def execute_run(factory, run_id: str, owner: str, *, pipeline: Pipeline = process_video, stop_flag: threading.Event | None = None,
                lease_s: float = store.LEASE_SECONDS, hb_interval_s: float | None = None) -> str:
    """Returns the final state. All outcomes are recorded in the database; nothing is raised for expected failures."""
    with session_scope(factory) as s:
        run, video = s.get(m.Run, run_id), None
        video = s.get(m.Video, run.video_id)
        settings = Settings.model_validate(run.config)
        zones = zones_from_dicts(run.zones)
        video_path = data_dir() / video.original_rel
        attempt_n = run.attempt
    cancel = threading.Event()
    done = threading.Event()
    interval = hb_interval_s if hb_interval_s is not None else max(0.2, lease_s / 3)

    def beat():
        while not done.wait(interval):
            try:
                if store.heartbeat(factory, run_id, owner, lease_s):
                    cancel.set()
            except Exception:
                pass                       # a transient failure is retried at the next beat; a lost lease is detected by the worker's final write

    th = threading.Thread(target=beat, daemon=True); th.start()
    last = {"n": -1}

    def progress(n: int, total: int, t_ms: int):
        if n - last["n"] >= 5:
            last["n"] = n
            store.heartbeat(factory, run_id, owner, lease_s, processed_ms=t_ms, progress=min(0.99, n / max(1, total)))

    def should_cancel() -> bool:
        if stop_flag is not None and stop_flag.is_set():
            raise Stopped()
        return cancel.is_set()

    try:
        res = pipeline(video_path, zones, settings, runs_dir(), run_id=run_id, attempt_n=attempt_n, on_progress=progress, should_cancel=should_cancel)
        return _publish(factory, run_id, owner, attempt_n, res)
    except Cancelled:
        def go():
            with session_scope(factory) as s:
                run = s.get(m.Run, run_id); run.state, run.lease_owner, run.finished_at = "cancelled", None, store.utcnow().replace(tzinfo=None)
        with_lock_retry(go); return "cancelled"
    except Stopped:
        _fail(factory, run_id, "worker_stopped", "The worker was stopped; restart the run to recompute from the beginning.", True, state="interrupted"); return "interrupted"
    except (MediaError, DetectorError) as e:
        _fail(factory, run_id, e.code, e.message, False); return "failed"
    except OSError as e:
        if e.errno == errno.ENOSPC:
            _fail(factory, run_id, "disk_full", "The disk is full. Free space, then restart the run.", False); return "failed"
        with session_scope(factory) as s:
            retries = s.get(m.Run, run_id).retry_count or 0
        if retries < 1:    # at most one automatic retry for a recognised transient storage error
            _fail(factory, run_id, "storage_error", f"Transient storage error, retrying once: {e}", True, requeue=True); return "queued"
        _fail(factory, run_id, "storage_error", f"Storage error after one retry: {e}", False); return "failed"
    except Exception as e:  # deterministic or unknown: do not retry
        _fail(factory, run_id, "internal_error", f"{type(e).__name__}: {e}", False); return "failed"
    finally:
        done.set(); th.join(timeout=2)


def _publish(factory, run_id: str, owner: str, attempt: int, res: dict) -> str:
    """Artifacts and the manifest already exist on disk. Only now does the database announce completion, in one transaction."""
    obs = [{"run_id": run_id, "attempt": attempt, "t_ms": o["t_ms"], "track_id": o["track_id"], "class_id": o["class_id"], "class_name": o["class_name"],
            "confidence": o["confidence"], "x1": o["box"][0], "y1": o["box"][1], "x2": o["box"][2], "y2": o["box"][3], "track_state": o["track_state"], "source": o["source"]}
           for o in res["observations"]]
    manifest_rel = str((Path(res["attempt_dir"]) / "manifest.json").relative_to(data_dir()))
    assert (data_dir() / manifest_rel).is_file(), "manifest must exist before completion is recorded"
    import hashlib

    def go():
        with session_scope(factory) as s:
            run = s.get(m.Run, run_id)
            if run.state != "running" or run.lease_owner != owner or run.attempt != attempt:
                return "lease_lost"           # another worker or a recovery took over; leave their state alone
            if obs:
                for i in range(0, len(obs), 2000):
                    s.execute(insert(m.Observation), obs[i:i + 2000])
            for e in res["events"]:
                s.add(m.Event(id=hashlib.sha1(f"{run_id}:{e['event_id']}".encode()).hexdigest()[:20], run_id=run_id, attempt=attempt, event_key=e["event_id"], type=e["type"],
                              zone_id=e["zone_id"], start_ms=e["start_ms"], end_ms=e["end_ms"], track_ids=e["track_ids"], class_name=e["class_name"], rule_version=e["rule_version"],
                              details=e["details"], uncertainty_flags=e["uncertainty_flags"], evidence=e["evidence"], description=e["description"], group_id=e["group_id"], source=e["source"]))
            run.state, run.progress, run.lease_owner, run.finished_at = "completed", 1.0, None, store.utcnow().replace(tzinfo=None)
            run.quality_flags, run.detector, run.timings = res["summary"]["quality_flags"], res["run_meta"]["detector"], res["run_meta"]["timings"]
            run.pipeline_version, run.manifest_rel, run.manifest_sha256 = res["run_meta"]["pipeline_version"], manifest_rel, res["manifest_sha256"]
            return "completed"
    return with_lock_retry(go)
