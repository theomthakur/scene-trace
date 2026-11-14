"""API and worker integration. Detections here come from a scripted FixtureDetector (source='fixture'); the real-detector flow is in test_real_inference.py."""
import functools, json, threading, time
import pytest
from fastapi.testclient import TestClient
from helpers import FixtureDetector, make_video, person_in_zone_script
from video_investigator.runner import process_video
from video_investigator.worker import jobs, store

ZONE = {"zones": [{"id": "z1", "name": "Centre zone", "role": "restricted", "polygon": [[0.3, 0.6], [0.7, 0.6], [0.7, 0.98], [0.3, 0.98]]}]}


def upload(client, tmp_path, name="clip.mp4", seconds=4.0):
    p = make_video(tmp_path / name, seconds=seconds)
    with open(p, "rb") as f:
        r = client.post("/api/videos", files={"file": (name, f, "video/mp4")}, data={"display_name": "Test clip"})
    assert r.status_code == 201, r.text
    return r.json()


def make_run(client, vid, **kw):
    assert client.put(f"/api/videos/{vid}/zones", json=ZONE).status_code == 200
    r = client.post("/api/runs", json={"video_id": vid, **kw}); assert r.status_code == 202, r.text
    return r.json()


def run_with_fixture(client, run_id, script=None, owner="t1"):
    f = client.app.state.factory
    run = store.claim_next(f, owner); assert run and run.id == run_id
    pipe = functools.partial(process_video, detector=FixtureDetector(script or person_in_zone_script()))
    return jobs.execute_run(f, run_id, owner, pipeline=pipe)


# ---------- upload, probe, playback ----------
def test_upload_probe_playback_range_semantics(client, tmp_path):
    v = upload(client, tmp_path)
    assert v["duration_ms"] in range(3900, 4200) and v["width"] == 320 and v["timestamps_ok"] is True
    got = client.get(f"/api/videos/{v['id']}").json()
    assert got["ready"] and got["media_url"] == f"/api/videos/{v['id']}/media"
    full = client.get(got["media_url"]); assert full.status_code == 200 and full.headers["accept-ranges"] == "bytes"
    size = len(full.content)
    part = client.get(got["media_url"], headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and part.headers["content-range"] == f"bytes 0-99/{size}" and len(part.content) == 100 and part.content == full.content[:100]
    tail = client.get(got["media_url"], headers={"Range": "bytes=-50"}); assert tail.status_code == 206 and tail.content == full.content[-50:]
    assert client.get(got["media_url"], headers={"Range": f"bytes={size + 10}-"}).status_code == 416
    assert client.get(got["media_url"], headers={"Range": "bytes=abc"}).status_code == 416
    assert str(tmp_path) not in json.dumps(got)          # never expose filesystem paths


def test_original_is_preserved_byte_for_byte(client, tmp_path, data_dir):
    p = make_video(tmp_path / "o.mp4")
    with open(p, "rb") as f:
        v = client.post("/api/videos", files={"file": ("o.mp4", f, "video/mp4")}).json()
    stored = next((data_dir / "videos" / v["id"]).glob("original.*"))
    assert stored.read_bytes() == p.read_bytes()


def test_invalid_uploads_have_explicit_outcomes(client, tmp_path, monkeypatch):
    r = client.post("/api/videos", files={"file": ("a.mp4", b"not a video at all", "video/mp4")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "not_a_video"          # renamed non-video
    good = make_video(tmp_path / "g.mp4").read_bytes()
    r = client.post("/api/videos", files={"file": ("t.mp4", good[:300], "video/mp4")}); assert r.status_code == 422                   # corrupt/truncated
    assert client.post("/api/videos", files={"file": ("e.mp4", b"", "video/mp4")}).status_code == 422
    monkeypatch.setenv("VI_UPLOAD_MAX_BYTES", "2000")
    from video_investigator.api.app import create_app
    with TestClient(create_app()) as small:
        r = small.post("/api/videos", files={"file": ("big.mp4", good, "video/mp4")})
        assert r.status_code == 413 and r.json()["error"]["code"] == "too_large"


def test_zone_validation_and_versions(client, tmp_path):
    v = upload(client, tmp_path)
    bad = {"zones": [{"id": "x", "name": "Bow", "role": "restricted", "polygon": [[0.1, 0.1], [0.9, 0.9], [0.9, 0.1], [0.1, 0.9]]}]}
    r = client.put(f"/api/videos/{v['id']}/zones", json=bad); assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_polygon"
    assert client.put(f"/api/videos/{v['id']}/zones", json={"zones": [{"id": "x", "name": "n", "role": "weird", "polygon": [[0, 0], [1, 0], [1, 1]]}]}).status_code == 422
    assert client.put(f"/api/videos/{v['id']}/zones", json=ZONE).json()["version"] == 1
    assert client.put(f"/api/videos/{v['id']}/zones", json=ZONE).json()["version"] == 2       # editing creates a new immutable version
    assert client.get(f"/api/videos/{v['id']}/zones?version=1").json()["version"] == 1
    assert client.put("/api/videos/nope/zones", json=ZONE).status_code == 404


def test_run_creation_rules_and_dedup(client, tmp_path):
    v = upload(client, tmp_path)
    r = client.post("/api/runs", json={"video_id": v["id"]}); assert r.status_code == 422 and r.json()["error"]["code"] == "zones_required"
    client.put(f"/api/videos/{v['id']}/zones", json=ZONE)
    a = client.post("/api/runs", json={"video_id": v["id"], "client_request_id": "req-1"}); b = client.post("/api/runs", json={"video_id": v["id"], "client_request_id": "req-1"})
    assert a.status_code == b.status_code == 202 and a.json()["id"] == b.json()["id"] and b.json()["deduplicated"] is True
    assert len(client.get("/api/runs").json()["runs"]) == 1
    assert client.post("/api/runs", json={"video_id": v["id"], "config_overrides": {"limits": {"upload_max_bytes": 1}}}).status_code == 422
    assert client.post("/api/runs", json={"video_id": v["id"], "config_overrides": {"detector": {"name": "x"}}}).status_code == 422
    assert client.post("/api/runs", json={"video_id": v["id"], "config_overrides": {"processing": {"sample_fps": 2}}}).status_code == 422   # gap rule needs >= 1/fps? 0.4 < 0.5
    ok = client.post("/api/runs", json={"video_id": v["id"], "config_overrides": {"detector": {"score_threshold": 0.7}}}); assert ok.status_code == 202
    assert client.post("/api/runs", json={"video_id": "missing"}).status_code == 404


def test_cancel_queued_and_terminal_state_semantics(client, tmp_path):
    v = upload(client, tmp_path); run = make_run(client, v["id"])
    assert client.post(f"/api/runs/{run['id']}/cancel").json()["state"] == "cancelled"
    assert client.post(f"/api/runs/{run['id']}/cancel").status_code == 409            # terminal stays terminal
    assert client.post("/api/runs/nope/cancel").status_code == 404
    assert client.post(f"/api/runs/{run['id']}/restart").status_code == 202
    assert client.get(f"/api/runs/{run['id']}").json()["state"] == "queued"


# ---------- full flow with the fixture detector ----------
def completed_run(client, tmp_path):
    v = upload(client, tmp_path); run = make_run(client, v["id"])
    assert run_with_fixture(client, run["id"]) == "completed"
    return v, run["id"]


def test_completed_run_events_observations_evidence_and_tagging(client, tmp_path):
    v, rid = completed_run(client, tmp_path)
    r = client.get(f"/api/runs/{rid}").json()
    assert r["state"] == "completed" and r["complete"] and r["manifest_sha256"] and r["attempt"] == 1
    ev = client.get(f"/api/runs/{rid}/events").json()
    assert ev["complete"] and ev["total"] == 1
    e = ev["events"][0]
    assert e["type"] == "zone_entry" and e["source"] == "fixture" and e["start_ms"] == 800 and e["end_ms"] == 3600           # tentative first hit is ignored
    obs = client.get(f"/api/runs/{rid}/observations?start_ms=1000&end_ms=2000").json()
    assert obs["complete"] and obs["observations"] and all(1000 <= o["t_ms"] <= 2000 for o in obs["observations"]) and all(o["source"] == "fixture" for o in obs["observations"])
    page = client.get(f"/api/runs/{rid}/observations?limit=3").json()
    assert len(page["observations"]) == 3 and page["next_cursor"]
    nxt = client.get(f"/api/runs/{rid}/observations?limit=3&cursor={page['next_cursor']}").json()
    assert nxt["observations"][0]["t_ms"] >= page["observations"][-1]["t_ms"]
    base = e["evidence_base"]
    assert client.get(base + "start.jpg").status_code == 200 and client.get(base + "clip.mp4").status_code == 200
    assert client.get(base + "../../run.json").status_code == 404 and client.get(base + "secret.txt").status_code == 404
    assert client.get(f"/api/runs/{rid}/evidence/{'0' * 12}/start.jpg").status_code == 404


def test_review_conflict_persistence_across_restart_and_export(client, tmp_path, data_dir):
    v, rid = completed_run(client, tmp_path)
    e = client.get(f"/api/runs/{rid}/events").json()["events"][0]
    ok = client.put(f"/api/events/{e['id']}/review", json={"verdict": "confirmed", "note": "visible", "expected_version": 0}); assert ok.status_code == 200 and ok.json()["review_version"] == 1
    stale = client.put(f"/api/events/{e['id']}/review", json={"verdict": "dismissed", "note": "", "expected_version": 0})
    assert stale.status_code == 409 and stale.json()["error"]["current_version"] == 1
    from video_investigator.api.app import create_app
    with TestClient(create_app()) as again:                      # a fresh app on the same database = a restart
        got = again.get(f"/api/runs/{rid}/events").json()["events"][0]
        assert got["review_status"] == "confirmed" and got["review_note"] == "visible"
        rep = again.get(f"/api/runs/{rid}/report").json()
        assert rep["video"]["source_sha256"] == v["source_sha256"] and rep["run"]["manifest_sha256"] and rep["limitations"] and rep["data_source"].startswith("contains fixture")
        md = again.get(f"/api/runs/{rid}/report?format=markdown").text
        assert "## Limitations" in md and v["source_sha256"] in md and "Source: fixture" in md
        assert again.get(f"/api/runs/{rid}/report?format=html").status_code == 200


def test_search_structured_text_and_unsupported(client, tmp_path):
    v, rid = completed_run(client, tmp_path)
    ok = client.post(f"/api/runs/{rid}/search", json={"query": "person entering the centre zone"}).json()
    assert len(ok["results"]) == 1 and "person" in ok["interpreted"]["classes"] and ok["interpreted"]["zone_ids"] == ["z1"] and not ok["unsupported"]
    assert client.post(f"/api/runs/{rid}/search", json={"filters": {"type": "stationary_object"}}).json()["results"] == []
    bad = client.post(f"/api/runs/{rid}/search", json={"query": "unattended bag"}).json()
    assert bad["results"] == [] and bad["unsupported"] and any("Unattended" in n for n in bad["notices"])
    nonsense = client.post(f"/api/runs/{rid}/search", json={"query": "purple elephants dancing"}).json()
    assert nonsense["results"] == [] and nonsense["unsupported"]
    assert client.post(f"/api/runs/{rid}/search", json={"query": "entry after 10 seconds"}).json()["results"] == []         # time constraint excludes the event
    assert len(client.post(f"/api/runs/{rid}/search", json={"query": "entry before 2 s"}).json()["results"]) == 1
    assert client.post(f"/api/runs/{rid}/search", json={"query": "x", "limit": 0}).status_code == 422


# ---------- failure handling ----------
def test_disk_exhaustion_fails_without_retry_and_exposes_nothing(client, tmp_path, monkeypatch):
    import errno
    from video_investigator.reports import artifacts
    v = upload(client, tmp_path); run = make_run(client, v["id"])
    real = artifacts.write_file
    def boom(path, data):
        if path.name == "observations.jsonl":
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(path, data)
    monkeypatch.setattr(artifacts, "write_file", boom)
    assert run_with_fixture(client, run["id"]) == "failed"
    r = client.get(f"/api/runs/{run['id']}").json()
    assert r["state"] == "failed" and r["errors"][0]["code"] == "disk_full" and r["retry_count"] == 0 and not r["complete"]
    assert client.get(f"/api/runs/{run['id']}/events").json()["events"] == [] and client.get(f"/api/runs/{run['id']}/report").status_code == 409


def test_one_automatic_retry_for_transient_storage_error_then_give_up(client, tmp_path, monkeypatch):
    import errno
    from video_investigator.reports import artifacts
    v = upload(client, tmp_path); run = make_run(client, v["id"])
    monkeypatch.setattr(artifacts, "write_file", lambda *a, **k: (_ for _ in ()).throw(OSError(errno.EIO, "I/O error")))
    assert run_with_fixture(client, run["id"], owner="a") == "queued"                    # first transient error: requeued once
    assert client.get(f"/api/runs/{run['id']}").json()["retry_count"] == 1
    assert run_with_fixture(client, run["id"], owner="b") == "failed"                    # second: no further retry


def test_missing_weights_fails_loudly_never_falls_back(client, tmp_path):
    from video_investigator.vision.detector import DetectorError
    def no_weights(*a, **k):
        raise DetectorError("weights_unavailable", "Could not load the pretrained weights: offline")
    v = upload(client, tmp_path); run = make_run(client, v["id"])
    f = client.app.state.factory; claimed = store.claim_next(f, "w")
    assert jobs.execute_run(f, claimed.id, "w", pipeline=no_weights) == "failed"
    r = client.get(f"/api/runs/{run['id']}").json()
    assert r["errors"][0]["code"] == "weights_unavailable" and r["errors"][0]["retryable"] is False


def test_manifest_must_exist_before_completion_is_recorded(client, tmp_path, data_dir):
    v = upload(client, tmp_path); run = make_run(client, v["id"])
    f = client.app.state.factory; claimed = store.claim_next(f, "w")
    fake = {"attempt_dir": data_dir / "runs" / run["id"] / "attempt-1", "observations": [], "events": [], "summary": {"quality_flags": []}, "run_meta": {}, "manifest_sha256": "x"}
    with pytest.raises(AssertionError):
        jobs._publish(f, claimed.id, "w", claimed.attempt, fake)
    assert client.get(f"/api/runs/{run['id']}").json()["state"] == "running"            # never announced


def test_cancel_running_run_stops_between_frames_and_leaves_no_manifest(client, tmp_path, data_dir):
    v = upload(client, tmp_path, seconds=8.0); run = make_run(client, v["id"])
    f = client.app.state.factory; claimed = store.claim_next(f, "w")
    started = threading.Event()
    def slow_script(k):
        started.set(); time.sleep(0.05); return []
    pipe = functools.partial(process_video, detector=FixtureDetector(slow_script))
    result = {}
    th = threading.Thread(target=lambda: result.update(state=jobs.execute_run(f, claimed.id, "w", pipeline=pipe, lease_s=3, hb_interval_s=0.1))); th.start()
    assert started.wait(10)
    assert client.post(f"/api/runs/{run['id']}/cancel").json()["cancel_requested"] is True
    th.join(30); assert result["state"] == "cancelled"
    assert client.get(f"/api/runs/{run['id']}").json()["state"] == "cancelled"
    attempt = data_dir / "runs" / run["id"] / "attempt-1"
    assert not (attempt / "manifest.json").exists()                                      # partial work is never published as complete
    assert next((data_dir / "videos" / v["id"]).glob("original.*")).exists()             # the original survives
    assert client.get(f"/api/runs/{run['id']}/events").json()["complete"] is False


def test_video_without_usable_timing_blocks_run_creation_with_an_actionable_code(client, tmp_path):
    from video_investigator.db import models as m
    from video_investigator.db.session import session_scope
    v = upload(client, tmp_path)
    client.put(f"/api/videos/{v['id']}/zones", json=ZONE)
    with session_scope(client.app.state.factory) as s:
        row = s.get(m.Video, v["id"]); row.meta = {**row.meta, "timestamps_ok": False}
    r = client.post("/api/runs", json={"video_id": v["id"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unsupported_timing" and "timing" in r.json()["error"]["message"]


def test_evaluation_endpoints_serve_only_the_allow_listed_committed_reports(client):
    ids = client.get("/api/evaluations").json()["evaluations"]
    assert "semantic-eval" in ids and "explanation-eval" in ids and "crosscam-eval" in ids        # committed evidence is listed
    assert client.get("/api/evaluations/semantic-eval").json()["queries"] == 11
    assert client.get("/api/evaluations/g0-doctor-pedestrian_area").status_code == 404              # other files under docs/evidence are not exposed
    assert client.get("/api/evaluations/..%2Fapp").status_code == 404
