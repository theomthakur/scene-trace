"""Typed API contracts. Positions are integer ms; boxes and zone points are normalized xyxy / xy in the upright frame."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class ZoneIn(BaseModel):
    id: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=80)
    role: Literal["restricted", "passage"]
    polygon: list[tuple[float, float]] = Field(min_length=3, max_length=64)


class ZonesPut(BaseModel):
    zones: list[ZoneIn] = Field(min_length=1, max_length=20)


class RunCreate(BaseModel):
    video_id: str
    zone_version: int | None = None
    config_overrides: dict = Field(default_factory=dict)
    client_request_id: str | None = Field(default=None, max_length=100)


class SearchBody(BaseModel):
    query: str | None = Field(default=None, max_length=300)
    filters: dict = Field(default_factory=dict)       # type, class_name, zone_id, review_status, after_ms, before_ms
    limit: int | None = Field(default=None, ge=1)


class ReviewPut(BaseModel):
    verdict: Literal["confirmed", "dismissed", "uncertain"]
    note: str = Field(default="", max_length=2000)
    expected_version: int = Field(ge=0)


class SemanticSearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    filters: dict = Field(default_factory=dict)
    limit: int | None = Field(default=None, ge=1)
    min_similarity: float | None = Field(default=None, ge=-1.0, le=1.0)
