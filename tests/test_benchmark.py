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


# ---------------- expansion (additional recordings) ----------------
def test_expansion_freeze_matches_the_manifest_and_config_and_the_first_benchmark_is_untouched():
    import hashlib
    from video_investigator.config import load_settings
    fr = json.loads((REPO / "fixtures" / "benchmark" / "FREEZE-2.json").read_text())
    assert fr["config_hash"] == load_settings().config_hash()
    assert fr["manifest_sha256"] == hashlib.sha256((REPO / "fixtures" / "benchmark" / "manifest_expansion.json").read_bytes()).hexdigest(), "the expansion manifest changed after its freeze"
    first = json.loads((REPO / "fixtures" / "benchmark" / "FREEZE.json").read_text())
    assert first["manifest_sha256"] == hashlib.sha256((REPO / "fixtures" / "benchmark" / "manifest.json").read_bytes()).hexdigest()   # the first benchmark is byte-identical


def test_expansion_scenes_never_overlap_each_other_or_the_first_benchmark():
    a = json.loads((REPO / "fixtures" / "benchmark" / "manifest.json").read_text()); b = json.loads((REPO / "fixtures" / "benchmark" / "manifest_expansion.json").read_text())
    scenes_a = {s["scene_id"] for s in a["sources"]}; by = {}
    for s in b["sources"]:
        by.setdefault(s["split"], set()).add(s["scene_id"])
        assert len(s["sha1"]) == 40 and any(k in s["license"] for k in ("CC0", "CC BY", "Public domain")) and s["author"] and s["source_page"].startswith("https://commons.wikimedia.org/")
    assert set(by) == {"development-2", "test-2"} and not (by["development-2"] & by["test-2"]) and not ((by["development-2"] | by["test-2"]) & scenes_a)


def test_second_test_set_refuses_a_second_run_and_a_changed_setup(tmp_path, monkeypatch):
    done = tmp_path / "t2.json"; done.write_text("{}"); monkeypatch.setattr(benchmark, "TEST2_RESULT", done)
    with pytest.raises(SystemExit) as e:
        benchmark.run_expansion(include_test2=True)
    assert "already evaluated" in str(e.value)


# ---------------- third batch: negatives and audited units ----------------
def _audit_unit(ids):
    return [{"unit": "u", "clip": "c", "pred": [{"event_id": i, "start_ms": 0, "end_ms": 1000, "track_ids": [1], "uncertainty_flags": []} for i in ids]}]


def test_audit_summary_never_assumes_unlabelled_events_are_correct(tmp_path, monkeypatch):
    labels = tmp_path / "l.json"; monkeypatch.setattr(benchmark, "AUDIT_LABELS", labels)
    labels.write_text(json.dumps({"events": {"a": {"label": "supported"}, "b": {"label": "supported"}, "c": {"label": "unsupported"}, "d": {"label": "ambiguous"}}}))
    s = benchmark.audit_summary(_audit_unit(["a", "b", "c", "d", "e"]))
    assert (s["supported"], s["unsupported"], s["ambiguous"], s["unlabelled"], s["predicted_events"]) == (2, 1, 1, 1, 5)
    assert s["audited_precision"]["value"] == pytest.approx(2 / 3) and s["audited_precision"]["denominator"] == 3        # ambiguous and unlabelled are excluded, not counted as correct
    assert "not measured" in s["recall"]


def test_audit_precision_is_undefined_when_nothing_is_decided(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "AUDIT_LABELS", tmp_path / "missing.json")
    s = benchmark.audit_summary(_audit_unit(["a", "b"]))
    assert s["unlabelled"] == 2 and s["audited_precision"]["value"] is None and "no decided" in s["audited_precision"]["undefined_reason"]
    assert benchmark.audit_summary([]) is None


def test_third_batch_freeze_matches_and_the_third_test_set_refuses_a_second_run(tmp_path, monkeypatch):
    import hashlib
    from video_investigator.config import load_settings
    fr = json.loads((REPO / "fixtures" / "benchmark" / "FREEZE-3.json").read_text())
    assert fr["config_hash"] == load_settings().config_hash() == json.loads((REPO / "fixtures" / "benchmark" / "FREEZE.json").read_text())["config_hash"]   # same setup as the first frozen test
    assert fr["manifest_sha256"] == hashlib.sha256((REPO / "fixtures" / "benchmark" / "manifest_reliability.json").read_bytes()).hexdigest()
    done = tmp_path / "t3.json"; done.write_text("{}"); monkeypatch.setattr(benchmark, "TEST3_RESULT", done)
    with pytest.raises(SystemExit) as e:
        benchmark.run_reliability(include_test3=True)
    assert "already evaluated" in str(e.value)


def test_scenes_are_disjoint_across_all_three_manifests_and_licences_are_open():
    scenes = {}
    for name in ("manifest.json", "manifest_expansion.json", "manifest_reliability.json"):
        for s in json.loads((REPO / "fixtures" / "benchmark" / name).read_text())["sources"]:
            assert s["scene_id"] not in scenes, f"{s['scene_id']} appears in {scenes.get(s['scene_id'])} and {name}"
            scenes[s["scene_id"]] = name
            assert len(s["sha1"]) == 40 and any(k in s["license"] for k in ("CC0", "CC BY", "Public domain"))
    assert len(scenes) == 8                                                                   # 2 original + 3 expansion + 3 third batch


def test_saved_audit_report_and_labels_agree_and_cover_every_event():
    rep = json.loads((REPO / "docs" / "evidence" / "benchmark-reliability.json").read_text())
    events = rep["lanes"]["test_3"]["audit"]["events"]; labels = json.loads((REPO / "fixtures" / "benchmark" / "audit_labels.json").read_text())["events"]
    assert {e["event_id"] for e in events} == set(labels), "every audited event needs a label and no label may be orphaned"
    assert all(v["label"] in ("supported", "unsupported", "ambiguous") and v["note"] for v in labels.values())
    a = rep["lanes"]["test_3"]["audit"]
    assert a["supported"] + a["unsupported"] + a["ambiguous"] == a["predicted_events"] == len(events) and a["unlabelled"] == 0


@pytest.mark.parametrize(
    ("command", "runner", "flag", "result_path", "report_name"),
    [
        ("cmd_evaluate_expansion", "run_expansion", "include_test2", "TEST2_RESULT", "benchmark-expansion"),
        ("cmd_evaluate_reliability", "run_reliability", "include_test3", "TEST3_RESULT", "benchmark-reliability"),
    ],
)
def test_dev_only_cli_run_preserves_frozen_reports(monkeypatch, tmp_path, command, runner, flag, result_path, report_name):
    from argparse import Namespace
    from video_investigator import cli
    from video_investigator.evaluation import benchmark

    canonical = tmp_path / f"{report_name}.json"
    canonical.write_text('{"frozen": true}')
    frozen = tmp_path / "frozen.json"
    frozen.write_text('{"frozen": true}')
    monkeypatch.setattr(benchmark, "EVIDENCE", tmp_path)
    monkeypatch.setattr(benchmark, result_path, frozen)
    monkeypatch.setattr(benchmark, runner, lambda **_: {"sample_counts": {}, "lanes": {}})

    assert getattr(cli, command)(Namespace(**{flag: False})) == 0
    assert canonical.read_text() == frozen.read_text() == '{"frozen": true}'
    assert (tmp_path / f"{report_name}-development.json").is_file()
