"""Versioned temporal rules. Pure functions over tracker observations; no detector, no I/O.

Time is integer milliseconds. Dwell is accumulated only across consecutive qualifying observations whose gap is <= max_gap.
A run may bridge a short run of non-qualifying observations (hysteresis) but bridged time never counts as dwell.
Observations from tentative tracks are ignored. A completed run with zero events is never proof of an incident-free video.
"""
from __future__ import annotations
import hashlib, math
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Iterable, Sequence
from ..config import Settings
from ..vision.tracker import Observation
from .geometry import Point, bottom_center, box_area, point_in_polygon, polygon_box_intersection_area

RULE_VERSION = "rules-1"
ZONE_ENTRY, STATIONARY, PASSAGE = "zone_entry", "stationary_object", "passage_occupancy"
TYPE_LABEL = {ZONE_ENTRY: "Restricted-zone entry", STATIONARY: "Stationary object candidate", PASSAGE: "Aisle occupancy candidate"}


@dataclass
class Zone:
    id: str
    name: str
    role: str                        # "restricted" or "passage"
    polygon: list[Point]


@dataclass
class Event:
    type: str
    zone_id: str | None
    start_ms: int
    end_ms: int
    track_ids: list[int]
    class_name: str
    rule_version: str
    details: dict
    uncertainty_flags: list[str] = field(default_factory=list)
    source: str = "detector"         # "detector" for real pixel inference, "fixture" for generated observations
    description: str = ""
    group_id: str = ""
    event_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _event_id(e: Event) -> str:
    key = f"{e.type}|{e.zone_id}|{','.join(map(str, e.track_ids))}|{e.start_ms}|{e.source}"
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def _by_track(obs: Iterable[Observation], classes: Sequence[str]) -> dict[int, list[Observation]]:
    out: dict[int, list[Observation]] = defaultdict(list)
    for o in obs:
        if o.track_state == "confirmed" and o.class_name in classes:
            out[o.track_id].append(o)
    for v in out.values():
        v.sort(key=lambda o: o.t_ms)
    return out


def build_runs(series: list[tuple[int, bool]], *, max_gap_ms: int, hysteresis_ms: int, min_dwell_ms: int):
    """Turn a time-ordered (t_ms, qualifies) series into runs. Returns [(start, end, dwell, closed_by)].

    closed_by is one of: gap, hysteresis, end_of_data. A run is reported only if dwell >= min_dwell_ms (equality counts).
    """
    runs = []
    cur = None
    prev_t = None
    prev_q = False

    def close(reason):
        nonlocal cur
        if cur and cur["dwell"] >= min_dwell_ms:
            runs.append((cur["start"], cur["last_q"], cur["dwell"], reason))
        cur = None

    for t, q in series:
        if cur is not None and prev_t is not None and t - prev_t > max_gap_ms:
            close("gap")
        if q:
            if cur is None:
                cur = {"start": t, "last_q": t, "dwell": 0}
            else:
                if prev_q and prev_t is not None:
                    cur["dwell"] += t - prev_t
                cur["last_q"] = t
        elif cur is not None and t - cur["last_q"] > hysteresis_ms:
            close("hysteresis")
        prev_t, prev_q = t, q
    close("end_of_data")
    return runs


def _flags(start_ms, end_ms, obs, video_start_ms, video_end_ms, reason, period_ms) -> list[str]:
    flags = []
    if start_ms - video_start_ms < period_ms * 1.5:
        flags.append("present_at_video_start")
    if reason == "end_of_data" and video_end_ms - end_ms < period_ms * 1.5:
        flags.append("still_active_at_video_end")
    elif reason in ("gap",):
        flags.append("track_lost_while_active")   # a lost track does not prove the object left
    return flags


def zone_entry_events(obs, zones: Sequence[Zone], s: Settings, *, video_start_ms=0, video_end_ms=0, source="detector") -> list[Event]:
    cfg, ev = s.events.zone_entry, s.events
    period = int(1000 / s.processing.sample_fps)
    out = []
    for z in (z for z in zones if z.role == "restricted"):
        for tid, series in _by_track(obs, cfg.classes).items():
            q = [(o.t_ms, point_in_polygon(bottom_center(o.box), z.polygon)) for o in series]
            for start, end, dwell, why in build_runs(q, max_gap_ms=int(ev.max_gap_s * 1000), hysteresis_ms=int(ev.exit_hysteresis_s * 1000), min_dwell_ms=int(cfg.dwell_s * 1000)):
                e = Event(ZONE_ENTRY, z.id, start, end, [tid], series[0].class_name, RULE_VERSION,
                          {"rule": "bottom-centre of the box inside the polygon (boundary counts)", "dwell_ms": dwell, "min_dwell_ms": int(cfg.dwell_s * 1000),
                           "zone_name": z.name, "coordinate_proxy": "bottom_center"},
                          _flags(start, end, series, video_start_ms, video_end_ms, why, period), source=source)
                e.description = f"{TYPE_LABEL[ZONE_ENTRY]}: {e.class_name} (track {tid}) in '{z.name}' from {start / 1000:.1f} s to {end / 1000:.1f} s"
                out.append(e)
    return out


def passage_events(obs, zones: Sequence[Zone], s: Settings, *, video_start_ms=0, video_end_ms=0, source="detector") -> list[Event]:
    cfg, ev = s.events.passage, s.events
    period = int(1000 / s.processing.sample_fps)
    out = []
    for z in (z for z in zones if z.role == "passage"):
        for tid, series in _by_track(obs, cfg.classes).items():
            fracs = {}
            q = []
            for o in series:
                a = box_area(o.box)
                f = polygon_box_intersection_area(z.polygon, o.box) / a if a > 0 else 0.0
                fracs[o.t_ms] = f
                q.append((o.t_ms, f >= cfg.min_overlap))
            for start, end, dwell, why in build_runs(q, max_gap_ms=int(ev.max_gap_s * 1000), hysteresis_ms=int(ev.exit_hysteresis_s * 1000), min_dwell_ms=int(cfg.persistence_s * 1000)):
                inside = [f for t, f in fracs.items() if start <= t <= end]
                e = Event(PASSAGE, z.id, start, end, [tid], series[0].class_name, RULE_VERSION,
                          {"rule": "object box overlaps the passage polygon by at least the threshold fraction of its own area (2D image overlap, not physical clearance)",
                           "min_overlap": cfg.min_overlap, "max_overlap_seen": round(max(inside), 3) if inside else None, "dwell_ms": dwell,
                           "min_persistence_ms": int(cfg.persistence_s * 1000), "zone_name": z.name, "assumption": "2D overlap only; perspective can mislead"},
                          _flags(start, end, series, video_start_ms, video_end_ms, why, period), source=source)
                e.description = f"{TYPE_LABEL[PASSAGE]}: {e.class_name} (track {tid}) overlapping '{z.name}' from {start / 1000:.1f} s to {end / 1000:.1f} s"
                out.append(e)
    return out


def stationary_events(obs, s: Settings, frame_size: tuple[int, int], *, video_start_ms=0, video_end_ms=0, source="detector") -> list[Event]:
    cfg, ev = s.events.stationary, s.events
    period = int(1000 / s.processing.sample_fps)
    w, h = frame_size
    diag = math.hypot(w, h)
    max_gap = int(ev.max_gap_s * 1000)
    min_ms = int(cfg.duration_s * 1000)
    out = []

    def emit(tid, cls, start, end, disp_max, why):
        if end - start >= min_ms:
            e = Event(STATIONARY, None, start, end, [tid], cls, RULE_VERSION,
                      {"rule": "box centre stays within the displacement threshold of the window start anchor", "window_ms": end - start, "min_window_ms": min_ms,
                       "max_displacement_diag": round(disp_max, 4), "threshold_diag": cfg.displacement_diag,
                       "person_association": "not assessed: a stationary object is not called unattended or abandoned"},
                      _flags(start, end, None, video_start_ms, video_end_ms, why, period), source=source)
            e.description = f"{TYPE_LABEL[STATIONARY]}: {cls} (track {tid}) approximately stationary from {start / 1000:.1f} s to {end / 1000:.1f} s"
            out.append(e)

    for tid, series in _by_track(obs, cfg.classes).items():
        anchor = series[0]; start = last = anchor.t_ms; disp_max = 0.0
        for o in series[1:]:
            cx, cy = (o.box[0] + o.box[2]) / 2 * w, (o.box[1] + o.box[3]) / 2 * h
            ax, ay = (anchor.box[0] + anchor.box[2]) / 2 * w, (anchor.box[1] + anchor.box[3]) / 2 * h
            d = math.hypot(cx - ax, cy - ay) / diag
            if o.t_ms - last > max_gap:
                emit(tid, anchor.class_name, start, last, disp_max, "gap"); anchor, start, last, disp_max = o, o.t_ms, o.t_ms, 0.0
            elif d > cfg.displacement_diag:
                emit(tid, anchor.class_name, start, last, disp_max, "moved"); anchor, start, last, disp_max = o, o.t_ms, o.t_ms, 0.0
            else:
                last = o.t_ms; disp_max = max(disp_max, d)
        emit(tid, anchor.class_name, start, last, disp_max, "end_of_data")
    return out


def assign_groups(events: list[Event]) -> None:
    """Events that share a track and overlap in time are grouped for display. They stay separate events, so nothing is double counted."""
    parent = list(range(len(events)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i

    for i, a in enumerate(events):
        for j in range(i + 1, len(events)):
            b = events[j]
            if set(a.track_ids) & set(b.track_ids) and a.start_ms <= b.end_ms and b.start_ms <= a.end_ms:
                parent[find(i)] = find(j)
    roots: dict[int, str] = {}
    for i, e in enumerate(events):
        r = find(i)
        roots.setdefault(r, f"g{len(roots) + 1}")
        e.group_id = roots[r]


def detect_events(obs: Sequence[Observation], zones: Sequence[Zone], s: Settings, frame_size: tuple[int, int], *,
                  video_start_ms: int = 0, video_end_ms: int = 0, source: str = "detector") -> list[Event]:
    events = (zone_entry_events(obs, zones, s, video_start_ms=video_start_ms, video_end_ms=video_end_ms, source=source)
              + passage_events(obs, zones, s, video_start_ms=video_start_ms, video_end_ms=video_end_ms, source=source)
              + stationary_events(obs, s, frame_size, video_start_ms=video_start_ms, video_end_ms=video_end_ms, source=source))
    events.sort(key=lambda e: (e.start_ms, e.type, e.track_ids))
    for e in events:
        e.event_id = _event_id(e)
    assign_groups(events)
    return events
