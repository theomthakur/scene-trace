"""Subprocess entry point for the kill/restart test: a worker whose pipeline is slow, so the test can SIGKILL it mid-run."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from video_investigator.db.session import make_engine, migrate, session_factory
from video_investigator.worker.main import run_forever


def slow_pipeline(video_path, zones, settings, out_root, *, run_id, attempt_n, on_progress, should_cancel, **kw):
    (out_root / run_id / f"attempt-{attempt_n}").mkdir(parents=True, exist_ok=True)       # partial work exists on disk, but no manifest
    for i in range(300):
        should_cancel(); on_progress(i + 1, 300, i * 100); time.sleep(0.1)
    raise RuntimeError("should have been killed before finishing")


if __name__ == "__main__":
    e = make_engine(); migrate(e)
    run_forever(session_factory(e), pipeline=slow_pipeline, owner="doomed-worker")
