import json, subprocess, sys
from pathlib import Path
import pytest
from video_investigator.evaluation import benchmark
from video_investigator.evaluation.matching import match, ratio, summarize, tiou

REPO = Path(__file__).resolve().parent.parent


def ev(t, z, s, e):
    return {"type": t, "zone_id": z, "start_ms": s, "end_ms": e}


def test_temporal_iou_and_threshold_equality():
    assert tiou((0, 1000), (500, 1500)) == pytest.approx(1 / 3)
    assert tiou((0, 1000), (0, 1000)) == 1.0 and tiou((0, 1000), (1000, 2000)) == 0.0
    m = match([ev("zone_entry", "z", 0, 1000)], [ev("zone_entry", "z", 500, 1000)], 0.5)      # IoU exactly 0.5 counts
    assert len(m["matches"]) == 1 and m["matches"][0]["onset_abs_error_ms"] == 500


def test_matching_is_one_to_one_and_requires_same_type_and_zone():
    pred = [ev("zone_entry", "z", 0, 1000), ev("zone_entry", "z", 0, 1000)]
    m = match(pred, [ev("zone_entry", "z", 0, 1000)])
    assert len(m["matches"]) == 1 and m["false_positives"] == [1]                       # a duplicate prediction is a false positive
    assert match([ev("zone_entry", "z2", 0, 1000)], [ev("zone_entry", "z", 0, 1000)])["missed"] == [0]
    assert match([ev("stationary_object", None, 0, 1000)], [ev("zone_entry", None, 0, 1000)])["missed"] == [0]


def test_empty_prediction_and_empty_truth_are_undefined_not_perfect():
    assert ratio(0, 0, "no predicted events") == {"value": None, "numerator": 0, "denominator": 0, "undefined_reason": "no predicted events"}
    s = summarize([match([], [])])
    assert s["precision"]["value"] is None and s["recall"]["value"] is None and s["false_alerts_per_negative_video_hour"]["value"] is None
    s = summarize([{**match([ev("a", None, 0, 10)], []), "negative": True, "hours": 0.01}])
    assert s["false_alerts_per_negative_video_hour"]["value"] == pytest.approx(100.0) and s["precision"]["value"] == 0.0 and s["recall"]["value"] is None
    s = summarize([{**match([], [ev("a", None, 0, 10)]), "negative": False, "hours": 0.01}])
    assert s["recall"]["value"] == 0.0 and s["precision"]["value"] is None


def test_fixture_report_reproduces_byte_for_byte():
    sys.path.insert(0, str(REPO / "scripts"))
    import make_fixture_report
    assert make_fixture_report.render() == (REPO / "fixtures" / "reports" / "fixture-report.json").read_text()


def test_the_manifest_is_consistent_and_splits_never_share_a_scene():
    m = json.loads((REPO / "fixtures" / "benchmark" / "manifest.json").read_text())
    by_split = {}
    for s in m["sources"]:
        by_split.setdefault(s["split"], set()).add(s["scene_id"])
        assert len(s["sha1"]) == 40 and s["license"].startswith("CC0") and (REPO / "fixtures" / "benchmark" / s["zones"]).is_file()
    assert not (by_split["development"] & by_split["test"])
    assert m["annotation"]["reviewers"] == 1 and "not expert consensus" in m["annotation"]["reviewer_note"]


def test_freeze_record_matches_current_config_and_manifest():
    import hashlib
    from video_investigator.config import load_settings
    fr = json.loads((REPO / "fixtures" / "benchmark" / "FREEZE.json").read_text())
    assert fr["config_hash"] == load_settings().config_hash(), "the configuration changed after the freeze"
    assert fr["manifest_sha256"] == hashlib.sha256((REPO / "fixtures" / "benchmark" / "manifest.json").read_bytes()).hexdigest(), "the manifest changed after the freeze"


def test_test_split_refuses_a_second_run(tmp_path, monkeypatch):
    done = tmp_path / "test-results.json"; done.write_text("{}")
    monkeypatch.setattr(benchmark, "TEST_RESULT", done)
    with pytest.raises(SystemExit) as e:
        benchmark.run_evaluation(include_test=True, with_sweep=False)
    assert "already evaluated" in str(e.value)


def test_no_persistence_baseline_removes_the_temporal_logic():
    from video_investigator.config import load_settings
    b = benchmark.baseline_settings(load_settings())
    assert b.events.zone_entry.dwell_s == 0 and b.events.passage.persistence_s == 0 and b.events.exit_hysteresis_s == 0
    assert b.events.stationary.duration_s == pytest.approx(0.2)
