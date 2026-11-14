"""Worker process: claims one queued run at a time and executes it. `python -m video_investigator.worker.main [--once]`."""
from __future__ import annotations
import argparse, os, signal, socket, threading, time, uuid
from ..db.session import make_engine, migrate, session_factory
from . import store
from .jobs import execute_run


def run_forever(factory, *, once: bool = False, poll_s: float = 0.5, owner: str | None = None, pipeline=None) -> list[str]:
    owner = owner or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    finished: list[str] = []
    recovered = store.recover_stale(factory)
    if recovered:
        print(f"recovered {len(recovered)} stale run(s) as interrupted: {recovered}", flush=True)
    while not stop.is_set():
        store.recover_stale(factory)
        run = store.claim_next(factory, owner)
        if run is None:
            if once:
                break
            stop.wait(poll_s); continue
        print(f"claimed run {run.id} attempt {run.attempt}", flush=True)
        kwargs = {"pipeline": pipeline} if pipeline else {}
        state = execute_run(factory, run.id, owner, stop_flag=stop, **kwargs)
        print(f"run {run.id} -> {state}", flush=True)
        finished.append(run.id)
    return finished


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="video_investigator.worker.main")
    ap.add_argument("--once", action="store_true", help="drain the queue and exit")
    args = ap.parse_args(argv)
    engine = make_engine(); migrate(engine)
    run_forever(session_factory(engine), once=args.once)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
