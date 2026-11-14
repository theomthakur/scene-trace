"""SQLAlchemy models. Video positions are integer milliseconds; audit timestamps are UTC; ids are UUID strings."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(timezone.utc)


def uid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Video(Base):
    __tablename__ = "videos"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    display_name: Mapped[str] = mapped_column(String(200))
    source_sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    meta: Mapped[dict] = mapped_column(JSON)                      # full probe result
    original_rel: Mapped[str] = mapped_column(String(300))        # relative to the data dir
    derivative_rel: Mapped[str | None] = mapped_column(String(300), nullable=True)
    derivative_status: Mapped[str] = mapped_column(String(20), default="preparing")   # preparing | ready | failed
    derivative_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=now)


class ZoneSet(Base):
    __tablename__ = "zone_sets"
    __table_args__ = (UniqueConstraint("video_id", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    zones: Mapped[list] = mapped_column(JSON)                     # immutable snapshot
    created_at: Mapped[datetime] = mapped_column(default=now)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id"), index=True)
    zone_version: Mapped[int] = mapped_column(Integer)
    zones: Mapped[list] = mapped_column(JSON)                     # frozen copy used by this run
    config: Mapped[dict] = mapped_column(JSON)                    # frozen settings used by this run
    config_hash: Mapped[str] = mapped_column(String(64))
    client_request_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    state: Mapped[str] = mapped_column(String(20), default="queued", index=True)   # queued running completed failed cancelled interrupted
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    processed_ms: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    quality_flags: Mapped[list] = mapped_column(JSON, default=list)
    detector: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    timings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    pipeline_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    manifest_rel: Mapped[str | None] = mapped_column(String(300), nullable=True)
    manifest_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=now)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (Index("ix_obs_run_attempt_t", "run_id", "attempt", "t_ms"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    attempt: Mapped[int] = mapped_column(Integer)
    t_ms: Mapped[int] = mapped_column(Integer)
    track_id: Mapped[int] = mapped_column(Integer)
    class_id: Mapped[int] = mapped_column(Integer)
    class_name: Mapped[str] = mapped_column(String(40))
    confidence: Mapped[float] = mapped_column(Float)
    x1: Mapped[float] = mapped_column(Float); y1: Mapped[float] = mapped_column(Float)
    x2: Mapped[float] = mapped_column(Float); y2: Mapped[float] = mapped_column(Float)
    track_state: Mapped[str] = mapped_column(String(12))
    source: Mapped[str] = mapped_column(String(10), default="detector")


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_ev_run_attempt", "run_id", "attempt", "start_ms"),)
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    attempt: Mapped[int] = mapped_column(Integer)
    event_key: Mapped[str] = mapped_column(String(20))
    type: Mapped[str] = mapped_column(String(30), index=True)
    zone_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    track_ids: Mapped[list] = mapped_column(JSON)
    class_name: Mapped[str] = mapped_column(String(40))
    rule_version: Mapped[str] = mapped_column(String(20))
    details: Mapped[dict] = mapped_column(JSON)
    uncertainty_flags: Mapped[list] = mapped_column(JSON)
    evidence: Mapped[dict] = mapped_column(JSON)
    description: Mapped[str] = mapped_column(Text)
    group_id: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(10), default="detector")
    review_status: Mapped[str] = mapped_column(String(12), default="unreviewed")   # unreviewed | confirmed | dismissed | uncertain
    review_note: Mapped[str] = mapped_column(Text, default="")
    review_version: Mapped[int] = mapped_column(Integer, default=0)
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), index=True)
    verdict: Mapped[str] = mapped_column(String(12))
    note: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(default=now)


class Explanation(Base):
    """Optional model-generated description of an event's evidence. Advisory: it never alters an event, a review or a report count."""
    __tablename__ = "explanations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    status: Mapped[str] = mapped_column(String(10))            # ok | flagged
    text: Mapped[str] = mapped_column(Text)
    flags: Mapped[list] = mapped_column(JSON)
    frames: Mapped[list] = mapped_column(JSON)
    labels: Mapped[list] = mapped_column(JSON)
    prompt: Mapped[str] = mapped_column(Text)
    prompt_sha256: Mapped[str] = mapped_column(String(64))
    model: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=now)
