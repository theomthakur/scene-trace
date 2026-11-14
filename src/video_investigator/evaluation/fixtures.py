"""Algorithm fixtures: generated observation trajectories with deterministic ground truth.

This lane tests the temporal rules WITHOUT a detector. Everything here is tagged source="fixture" and must never be reported
as end-to-end video evidence or mixed with real-inference metrics.
"""
from __future__ import annotations
import random
from dataclasses import dataclass
from ..vision.tracker import Observation
from ..events.rules import PASSAGE, STATIONARY, ZONE_ENTRY, Zone

FRAME = (960, 540)
RESTRICTED = Zone("z1", "Restricted A", "restricted", [(0.4, 0.5), (0.8, 0.5), (0.8, 0.95), (0.4, 0.95)])
PASSAGE_Z = Zone("p1", "Passage B", "passage", [(0.0, 0.55), (1.0, 0.55), (1.0, 0.9), (0.0, 0.9)])


@dataclass
class Scenario:
    name: str
    observations: list[Observation]
    zones: list[Zone]
    truth: list[dict]        # expected events: type, zone_id, start_ms, end_ms (tracks are implied by the scenario)
    purpose: str
    duration_ms: int
    sample_fps: float = 5.0


def box_at_feet(x: float, y: float, w=0.06, h=0.2):
    """A box whose bottom-centre is (x, y)."""
    return (x - w / 2, y - h, x + w / 2, y)


def _obs(t, tid, cls, box, state="confirmed", conf=0.9):
    return Observation(t, tid, {"person": 1, "car": 3, "handbag": 31}.get(cls, 0), cls, conf, tuple(box), state)


def walk(tid, cls, t0, t1, p0, p1, fps, *, jitter=0.0, seed=0, w=0.06, h=0.2, skip=()):
    rnd = random.Random(seed)
    step = int(1000 / fps)
    out = []
    t = t0
    while t <= t1:
        if not any(a <= t <= b for a, b in skip):
            f = (t - t0) / max(1, t1 - t0)
            x = p0[0] + (p1[0] - p0[0]) * f + rnd.uniform(-jitter, jitter)
            y = p0[1] + (p1[1] - p0[1]) * f + rnd.uniform(-jitter, jitter)
            out.append(_obs(t, tid, cls, box_at_feet(x, y, w, h)))
        t += step
    return out


def scenarios() -> list[Scenario]:
    S = []
    # 1 empty scene: no observations; the rules must return nothing (and this is NOT a certified incident-free video)
    S.append(Scenario("empty", [], [RESTRICTED], [], "empty input yields no events", 10000))
    # 2 clear entry: enters the restricted zone at 3.0 s, drifts across it and leaves through the far edge (last inside observation 9.2 s)
    o = walk(1, "person", 0, 3000, (0.1, 0.8), (0.4, 0.8), 5)[:-1] + walk(1, "person", 3000, 8000, (0.4, 0.8), (0.6, 0.8), 5) + walk(1, "person", 8200, 10000, (0.6, 0.8), (0.95, 0.8), 5)
    S.append(Scenario("clear_entry", o, [RESTRICTED], [{"type": ZONE_ENTRY, "zone_id": "z1", "start_ms": 3000, "end_ms": 9200}], "one entry, one event, no repeat per frame", 10000))
    # 3 brief crossing shorter than the dwell: no event
    o = walk(2, "person", 0, 1200, (0.3, 0.8), (0.9, 0.8), 5)   # inside the zone from 0.2 s to 1.0 s: 0.8 s, under the 1.0 s dwell
    S.append(Scenario("brief_crossing", o, [RESTRICTED], [], "crossing under the 1.0 s dwell is suppressed", 1200))
    # 4 boundary grazing: stays exactly on the boundary x=0.4 for 3 s (boundary counts as inside)
    o = [_obs(t, 3, "person", box_at_feet(0.4, 0.8)) for t in range(0, 3001, 200)]
    S.append(Scenario("boundary_grazing", o, [RESTRICTED], [{"type": ZONE_ENTRY, "zone_id": "z1", "start_ms": 0, "end_ms": 3000}], "boundary points count as inside", 3000))
    # 5 flicker: alternates in/out of the zone every frame; consecutive qualifying observations never occur, so no dwell accumulates
    o = [_obs(t, 4, "person", box_at_feet(0.41 if (t // 200) % 2 == 0 else 0.39, 0.8)) for t in range(0, 4001, 200)]
    S.append(Scenario("flicker", o, [RESTRICTED], [], "alternating boundary noise does not create an event", 4000))
    # 6 occlusion gap: inside 0-2 s, missing 2.0-3.0 s, inside again 3.0-5 s; the gap breaks the candidate, neither half reaches... first half 2.0 s dwell qualifies
    o = walk(5, "person", 0, 5000, (0.5, 0.8), (0.6, 0.8), 5, skip=[(2200, 2800)])
    S.append(Scenario("occlusion_gap", o, [RESTRICTED], [{"type": ZONE_ENTRY, "zone_id": "z1", "start_ms": 0, "end_ms": 2000}, {"type": ZONE_ENTRY, "zone_id": "z1", "start_ms": 3000, "end_ms": 5000}],
                      "a gap longer than 0.4 s splits the occupancy and missed time does not count as dwell", 5000))
    # 7 stationary object: a handbag sits for 8 s; a walking person passes (not a candidate: person excluded and moving)
    o = [_obs(t, 6, "handbag", box_at_feet(0.5, 0.7, 0.05, 0.05)) for t in range(0, 8001, 200)] + walk(7, "person", 0, 8000, (0.05, 0.6), (0.95, 0.6), 5)
    S.append(Scenario("stationary_object", o, [], [{"type": STATIONARY, "zone_id": None, "start_ms": 0, "end_ms": 8000}], "stationary candidate for a supported object; people excluded", 8000))
    # 8 jittery stationary object: jitter inside the displacement threshold still counts as stationary
    o = [_obs(t, 8, "handbag", box_at_feet(0.5 + (0.002 if (t // 200) % 2 else -0.002), 0.7, 0.05, 0.05)) for t in range(0, 7001, 200)]
    S.append(Scenario("stationary_jitter", o, [], [{"type": STATIONARY, "zone_id": None, "start_ms": 0, "end_ms": 7000}], "small jitter does not reset the window", 7000))
    # 9 overlapping rules: a parked car sits in the passage; both types are reported separately, never merged
    o = [_obs(t, 9, "car", box_at_feet(0.5, 0.85, 0.2, 0.2)) for t in range(0, 9001, 200)]
    S.append(Scenario("overlapping_rules", o, [PASSAGE_Z], [{"type": PASSAGE, "zone_id": "p1", "start_ms": 0, "end_ms": 9000}, {"type": STATIONARY, "zone_id": None, "start_ms": 0, "end_ms": 9000}],
                      "one interval can satisfy two rules; both are kept as separate events", 9000))
    # 10 frame-rate variation: the same 3 s dwell sampled at 10 fps
    o = walk(10, "person", 0, 3000, (0.5, 0.8), (0.55, 0.8), 10)
    S.append(Scenario("frame_rate_10fps", o, [RESTRICTED], [{"type": ZONE_ENTRY, "zone_id": "z1", "start_ms": 0, "end_ms": 3000}], "dwell is measured in seconds, not frames", 3000, sample_fps=10.0))
    # 11 tentative-only track: ignored
    o = [_obs(t, 11, "person", box_at_feet(0.5, 0.8), state="tentative") for t in range(0, 4001, 200)]
    S.append(Scenario("tentative_only", o, [RESTRICTED], [], "tentative tracks never produce events", 4000))
    # 12 two different tracks occupy the zone one after another: two events, never merged across track IDs
    o = walk(12, "person", 0, 2000, (0.5, 0.8), (0.5, 0.8), 5) + walk(13, "person", 2200, 4400, (0.5, 0.8), (0.5, 0.8), 5)
    S.append(Scenario("two_tracks_no_merge", o, [RESTRICTED], [{"type": ZONE_ENTRY, "zone_id": "z1", "start_ms": 0, "end_ms": 2000}, {"type": ZONE_ENTRY, "zone_id": "z1", "start_ms": 2200, "end_ms": 4400}],
                      "events are not merged across different track IDs", 4400))
    return S
