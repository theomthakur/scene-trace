"""Durable job store operations on the runs table. Claims are single atomic UPDATE statements (short write transactions)."""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
from sqlalchemy import text, update, select
from ..db import models as m
from ..db.session import session_scope, with_lock_retry

LEASE_SECONDS = float(os.environ.get("VI_LEASE_SECONDS", "30"))
TERMINAL = ("completed", "failed", "cancelled")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def claim_next(factory, owner: str, lease_s: float = LEASE_SECONDS) -> m.Run | None:
    """Atomically move the oldest queued run to running, only if no other run holds a live lease (one active inference job)."""
    now = utcnow().replace(tzinfo=None)
    exp = (utcnow() + timedelta(seconds=lease_s)).replace(tzinfo=None)

    def go():
        with session_scope(factory) as s:
            row = s.execute(text(
                "UPDATE runs SET state='running', lease_owner=:o, lease_expires_at=:exp, attempt=attempt+1, started_at=:now, cancel_requested=0, "
                "processed_ms=0, progress=0.0 "
                "WHERE id=(SELECT id FROM runs WHERE state='queued' ORDER BY created_at LIMIT 1) "
                "AND NOT EXISTS (SELECT 1 FROM runs WHERE state='running' AND lease_expires_at > :now) RETURNING id"),
                {"o": owner, "exp": exp, "now": now}).fetchone()
            return row[0] if row else None
    run_id = with_lock_retry(go)
    if not run_id:
        return None
    with session_scope(factory) as s:
        return s.get(m.Run, run_id)


def heartbeat(factory, run_id: str, owner: str, lease_s: float = LEASE_SECONDS, **progress) -> bool:
    """Extend the lease and optionally record progress. Returns the cancel_requested flag. Returns True (stop) if the lease was lost."""
    exp = (utcnow() + timedelta(seconds=lease_s)).replace(tzinfo=None)

    def go():
        with session_scope(factory) as s:
            vals = {"lease_expires_at": exp, **progress}
            res = s.execute(update(m.Run).where(m.Run.id == run_id, m.Run.lease_owner == owner, m.Run.state == "running").values(**vals))
            if res.rowcount == 0:
                return True
            return bool(s.execute(select(m.Run.cancel_requested).where(m.Run.id == run_id)).scalar())
    return with_lock_retry(go)


def recover_stale(factory) -> list[str]:
    """Running runs whose lease expired become 'interrupted'. They are never left running forever."""
    now = utcnow().replace(tzinfo=None)

    def go():
        with session_scope(factory) as s:
            ids = [r[0] for r in s.execute(text("UPDATE runs SET state='interrupted', lease_owner=NULL, finished_at=:now "
                                                "WHERE state='running' AND (lease_expires_at IS NULL OR lease_expires_at < :now) RETURNING id"), {"now": now}).fetchall()]
            for rid in ids:
                run = s.get(m.Run, rid)
                run.errors = [*(run.errors or []), {"code": "worker_lost", "retryable": True,
                                                    "message": "The worker stopped or crashed before finishing; restart the run to recompute from the beginning."}]
            return ids
    return with_lock_retry(go)


def request_cancel(factory, run_id: str) -> tuple[str, bool]:
    """Returns (state, accepted). Queued runs cancel immediately; running runs are flagged and stop between frames; terminal runs stay terminal."""
    def go():
        with session_scope(factory) as s:
            run = s.get(m.Run, run_id)
            if run is None:
                raise KeyError(run_id)
            if run.state == "queued":
                run.state, run.finished_at = "cancelled", utcnow().replace(tzinfo=None)
                return run.state, True
            if run.state == "running":
                run.cancel_requested = True
                return run.state, True
            return run.state, False
    return with_lock_retry(go)


def restart_run(factory, run_id: str) -> tuple[str, bool]:
    """interrupted, cancelled or failed -> queued; the next attempt recomputes from the beginning in a new attempt directory."""
    def go():
        with session_scope(factory) as s:
            run = s.get(m.Run, run_id)
            if run is None:
                raise KeyError(run_id)
            if run.state not in ("interrupted", "cancelled", "failed"):
                return run.state, False
            run.state, run.cancel_requested, run.finished_at, run.lease_owner = "queued", False, None, None
            return run.state, True
    return with_lock_retry(go)
