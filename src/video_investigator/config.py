"""Validated, versioned runtime settings loaded from YAML. A run stores a frozen copy and its hash."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
from typing import Any
import yaml
from pydantic import BaseModel, Field, model_validator

REPO = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO / "config" / "default.yaml"


class Limits(BaseModel):
    upload_max_bytes: int = Field(gt=0)
    upload_max_seconds: float = Field(gt=0)


class Processing(BaseModel):
    max_long_edge_px: int = Field(ge=64)
    sample_fps: float = Field(gt=0, le=30)


class Detector(BaseModel):
    name: str
    weights: str
    score_threshold: float = Field(ge=0, le=1)
    device: str = "cpu"
    classes: list[str]


class Tracker(BaseModel):
    iou_gate: float = Field(gt=0, lt=1)
    max_missing_s: float = Field(gt=0)
    min_hits_to_confirm: int = Field(ge=1)
    velocity_smoothing: float = Field(ge=0, le=1)


class ZoneEntry(BaseModel):
    dwell_s: float = Field(ge=0)
    classes: list[str]


class Stationary(BaseModel):
    duration_s: float = Field(gt=0)
    displacement_diag: float = Field(gt=0)
    classes: list[str]


class Passage(BaseModel):
    min_overlap: float = Field(gt=0, le=1)
    persistence_s: float = Field(ge=0)
    classes: list[str]


class Events(BaseModel):
    evidence_padding_s: float = Field(ge=0)
    max_gap_s: float = Field(gt=0)
    exit_hysteresis_s: float = Field(ge=0)
    zone_entry: ZoneEntry
    stationary: Stationary
    passage: Passage


class Search(BaseModel):
    default_limit: int = Field(ge=1)
    max_limit: int = Field(ge=1)


class Quality(BaseModel):
    sparse_detections_per_frame: float = Field(ge=0)
    long_gap_factor: float = Field(gt=1)


class Settings(BaseModel):
    config_version: str
    limits: Limits
    processing: Processing
    detector: Detector
    tracker: Tracker
    events: Events
    search: Search
    quality: Quality

    @model_validator(mode="after")
    def _joint(self) -> "Settings":
        # The gap rule and the sampling rate are configured jointly: a gap shorter than one sampling period would break every candidate.
        period = 1.0 / self.processing.sample_fps
        if self.events.max_gap_s + 1e-9 < period:
            raise ValueError(f"events.max_gap_s ({self.events.max_gap_s}) must be >= 1/sample_fps ({period:.3f})")
        if self.search.default_limit > self.search.max_limit:
            raise ValueError("search.default_limit exceeds search.max_limit")
        return self

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"))

    def config_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_settings(path: Path | str | None = None, overrides: dict[str, Any] | None = None) -> Settings:
    data = yaml.safe_load(Path(path or DEFAULT_CONFIG).read_text())
    if overrides:
        data = _merge(data, overrides)
    return Settings.model_validate(data)
