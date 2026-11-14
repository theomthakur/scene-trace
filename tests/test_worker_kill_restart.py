import functools, os, signal, subprocess, sys, time
from pathlib import Path
from helpers import FixtureDetector, make_video, person_in_zone_script
from test_api_flow import ZONE, make_run, upload
from video_investigator.runner import process_video
from video_investigator.worker import jobs, store


def test_kill_mid_run_then_restart_preserves_originals_and_never_exposes_partial_results(client, tmp_path, data_dir, monkeypatch):
    monkeypatch.setenv("VI_LEASE_SECONDS", "2")
    v = upload(client, tmp_path); run = make_run(client, v["id"])
    env = {**os.environ, "VI_DATA_DIR": str(data_dir), "VI_LEASE_SECONDS": "2"}
    proc = subprocess.Popen([sys.executable, str(Path(__file__).parent / "worker_slow.py")], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.time() + 30
        while time.time() < deadline and client.get(f"/api/runs/{run['id']}").json()["state"] != "running":
            time.sleep(0.1)
        assert client.get(f"/api/runs/{run['id']}").json()["state"] == "running"
        time.sleep(0.5)
        proc.send_signal(signal.SIGKILL); proc.wait(10)
    finally:
        if proc.poll() is None:
            proc.kill()
    # right after the kill the lease is still valid, so the run still says running; the lease then expires
    time.sleep(2.6)
    f = client.app.state.factory
    assert store.recover_stale(f) == [run["id"]]
    r = client.get(f"/api/runs/{run['id']}").json()
    assert r["state"] == "interrupted" and r["errors"][0]["code"] == "worker_lost" and r["errors"][0]["retryable"] is True and not r["complete"]
    ev = client.get(f"/api/runs/{run['id']}/events").json()
    assert ev["complete"] is False and ev["events"] == []
    assert client.get(f"/api/runs/{run['id']}/report").status_code == 409
    attempt1 = data_dir / "runs" / run["id"] / "attempt-1"
    assert attempt1.is_dir() and not (attempt1 / "manifest.json").exists()
    assert next((data_dir / "videos" / v["id"]).glob("original.*")).read_bytes() == (tmp_path / "clip.mp4").read_bytes()
    # restart creates a fresh attempt and recomputes from the beginning
    assert client.post(f"/api/runs/{run['id']}/restart").status_code == 202
    claimed = store.claim_next(f, "w2"); assert claimed.id == run["id"] and claimed.attempt == 2
    pipe = functools.partial(process_video, detector=FixtureDetector(person_in_zone_script()))
    assert jobs.execute_run(f, run["id"], "w2", pipeline=pipe) == "completed"
    r = client.get(f"/api/runs/{run['id']}").json()
    assert r["attempt"] == 2 and r["complete"]
    assert (data_dir / "runs" / run["id"] / "attempt-2" / "manifest.json").exists() and not (attempt1 / "manifest.json").exists()
    assert client.get(f"/api/runs/{run['id']}/events").json()["total"] == 1                 # events come from attempt 2 only, no duplicates


def test_only_one_active_job_and_oldest_first(client, tmp_path):
    v = upload(client, tmp_path)
    client.put(f"/api/videos/{v['id']}/zones", json=ZONE)
    a = client.post("/api/runs", json={"video_id": v["id"]}).json(); b = client.post("/api/runs", json={"video_id": v["id"]}).json()
    f = client.app.state.factory
    first = store.claim_next(f, "w1"); assert first.id == a["id"]
    assert store.claim_next(f, "w2") is None                              # a live lease blocks a second concurrent inference job
    assert client.get(f"/api/runs/{b['id']}").json()["state"] == "queued"


def test_stale_lease_is_not_left_running_forever(client, tmp_path):
    v = upload(client, tmp_path); run = make_run(client, v["id"])
    f = client.app.state.factory
    store.claim_next(f, "w1", lease_s=0.2); time.sleep(0.5)
    assert store.recover_stale(f) == [run["id"]]
    assert store.recover_stale(f) == []                                   # idempotent
