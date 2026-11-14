"""Fixture-lane tests: rules run on generated observations (no detector). Each scenario has deterministic ground truth."""
import pytest
from video_investigator.config import load_settings
from video_investigator.events.rules import detect_events
from video_investigator.evaluation.fixtures import FRAME, scenarios
from video_investigator.evaluation.matching import match


def settings_for(sc):
    return load_settings(overrides={"processing": {"sample_fps": sc.sample_fps}})


@pytest.mark.parametrize("sc", scenarios(), ids=lambda s: s.name)
def test_scenario_matches_ground_truth_exactly(sc):
    ev = detect_events(sc.observations, sc.zones, settings_for(sc), FRAME, video_start_ms=0, video_end_ms=sc.duration_ms, source="fixture")
    pred = [{"type": e.type, "zone_id": e.zone_id, "start_ms": e.start_ms, "end_ms": e.end_ms} for e in ev]
    m = match(pred, sc.truth, iou_threshold=0.99)
    assert not m["false_positives"] and not m["missed"], (sc.name, pred, sc.truth)
    assert all(e.source == "fixture" for e in ev)


def test_dwell_equality_counts_and_one_ms_short_does_not():
    from video_investigator.events.rules import build_runs
    series = [(t, True) for t in range(0, 1001, 200)]
    assert len(build_runs(series, max_gap_ms=400, hysteresis_ms=400, min_dwell_ms=1000)) == 1       # exactly 1.0 s
    assert build_runs(series, max_gap_ms=400, hysteresis_ms=400, min_dwell_ms=1001) == []           # one ms over


def test_gap_equal_to_limit_bridges_and_longer_gap_breaks():
    from video_investigator.events.rules import build_runs
    ok = [(0, True), (400, True), (800, True), (1200, True)]
    assert len(build_runs(ok, max_gap_ms=400, hysteresis_ms=0, min_dwell_ms=1000)) == 1
    broken = [(0, True), (200, True), (700, True), (900, True)]
    assert build_runs(broken, max_gap_ms=400, hysteresis_ms=0, min_dwell_ms=1000) == []


def test_hysteresis_bridges_short_exit_but_bridged_time_is_not_dwell():
    from video_investigator.events.rules import build_runs
    s = [(0, True), (200, True), (400, False), (600, True), (800, True), (1000, True)]
    runs = build_runs(s, max_gap_ms=400, hysteresis_ms=400, min_dwell_ms=0)
    assert len(runs) == 1 and runs[0][0] == 0 and runs[0][1] == 1000
    assert runs[0][2] == 200 + 200 + 200       # (0-200), (600-800), (800-1000); the bridged 200-600 is excluded


def test_no_persistence_baseline_overreports_flicker():
    """The temporal logic matters: with dwell removed, flicker and brief crossings become false alerts."""
    from video_investigator.evaluation.fixtures import scenarios as sc_all
    base = load_settings(overrides={"events": {"zone_entry": {"dwell_s": 0.0}, "exit_hysteresis_s": 0.0}})
    flicker = next(s for s in sc_all() if s.name == "flicker")
    assert detect_events(flicker.observations, flicker.zones, base, FRAME, video_end_ms=flicker.duration_ms, source="fixture")   # baseline fires
    full = load_settings()
    assert not detect_events(flicker.observations, flicker.zones, full, FRAME, video_end_ms=flicker.duration_ms, source="fixture")


def test_events_have_stable_ids_and_groups():
    sc = next(s for s in scenarios() if s.name == "overlapping_rules")
    a = detect_events(sc.observations, sc.zones, settings_for(sc), FRAME, video_end_ms=sc.duration_ms, source="fixture")
    b = detect_events(sc.observations, sc.zones, settings_for(sc), FRAME, video_end_ms=sc.duration_ms, source="fixture")
    assert [e.event_id for e in a] == [e.event_id for e in b] and len({e.event_id for e in a}) == 2
    assert len({e.group_id for e in a}) == 1            # one visual group, two separate event types
