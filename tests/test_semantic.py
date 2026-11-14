"""Semantic retrieval tests. The embedder here is a deterministic test double tagged source='fixture': it checks ranking, traceability, filtering,
persistence and failure behaviour. It says NOTHING about retrieval quality; that is measured with the real model in test_real_inference.py."""
import json
import numpy as np
import pytest
from PIL import Image
from helpers import person_in_zone_script
from test_api_flow import make_run, run_with_fixture, upload
from video_investigator.search import semantic


class FixtureEmbedder:
    """Images embed to their mean colour, texts to a colour keyword, in a 3-d space. Deterministic and obviously fake."""
    name, revision, dim, source = "fixture-colour-embedder", "0", 3, "fixture"
    COLOURS = {"red": (1, 0, 0), "green": (0, 1, 0), "blue": (0, 0, 1), "gray": (1, 1, 1), "grey": (1, 1, 1)}

    def embed_images(self, images):
        out = []
        for im in images:
            a = np.asarray(im.convert("RGB"), "float32").reshape(-1, 3).mean(0) + 1e-3
            out.append(a / np.linalg.norm(a))
        return np.array(out, "float32").reshape(-1, 3)

    def embed_texts(self, texts):
        out = []
        for t in texts:
            v = np.zeros(3, "float32")
            for w, c in self.COLOURS.items():
                if w in t.lower(): v += np.array(c, "float32")
            out.append(v / max(np.linalg.norm(v), 1e-6))
        return np.array(out, "float32").reshape(-1, 3)


def synthetic_attempt(tmp_path):
    """A hand-built attempt: 3 events with solid red, green and blue evidence frames, all on one track each."""
    att = tmp_path / "attempt-1"; events, obs = [], []
    for i, (name, rgb) in enumerate([("aaaaaaaaaaaa", (230, 20, 20)), ("bbbbbbbbbbbb", (20, 230, 20)), ("cccccccccccc", (20, 20, 230))]):
        (att / "evidence" / name).mkdir(parents=True)
        Image.new("RGB", (320, 180), rgb).save(att / "evidence" / name / "mid_original.jpg")
        events.append({"event_key": name, "track_ids": [i + 1], "evidence": {"frames": [{"role": "mid", "t_ms": 1000, "original": f"evidence/{name}/mid_original.jpg"}]}})
        obs.append({"t_ms": 1000, "track_id": i + 1, "track_state": "confirmed", "box": [0.2, 0.2, 0.8, 0.9]})
    return att, events, obs


def test_ranking_orders_by_similarity_and_names_the_exact_evidence_item(tmp_path):
    att, events, obs = synthetic_attempt(tmp_path); e = FixtureEmbedder()
    meta = semantic.build_index(att, events, obs, e, run_id="r", manifest_sha256="m1")
    assert meta["model"]["source"] == "fixture" and len(meta["items"]) == 6                       # 3 frames + 3 crops
    got = semantic.load_index(att, "m1"); assert got is not None
    ranked = semantic.rank_events(got[0], got[1], e.embed_texts(["a red thing"])[0], None, 10)
    assert [r["event_key"] for r in ranked] == ["aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc"][:1] + [r["event_key"] for r in ranked[1:]]
    assert ranked[0]["rank"] == 1 and ranked[0]["similarity"] > ranked[1]["similarity"] > -1.0
    b = ranked[0]["best"]; assert b["t_ms"] == 1000 and b["role"] == "mid" and b["kind"] in ("crop", "frame") and (b["kind"] == "frame" or len(b["box"]) == 4)
    only_blue = semantic.rank_events(got[0], got[1], e.embed_texts(["red"])[0], {"cccccccccccc"}, 10)
    assert [r["event_key"] for r in only_blue] == ["cccccccccccc"]                                  # restricting the pool restricts the ranking
    assert semantic.rank_events(got[0], got[1], e.embed_texts(["red"])[0], None, 1)[0]["event_key"] == "aaaaaaaaaaaa"
    assert semantic.rank_events(got[0], got[1], e.embed_texts(["red"])[0], None, 10, min_similarity=0.99)[0]["event_key"] == "aaaaaaaaaaaa"


def test_index_is_invalidated_when_the_source_manifest_or_the_file_changes(tmp_path):
    att, events, obs = synthetic_attempt(tmp_path); e = FixtureEmbedder()
    semantic.build_index(att, events, obs, e, run_id="r", manifest_sha256="m1")
    assert semantic.load_index(att, "m1") is not None and semantic.load_index(att, "different-manifest") is None
    np.save(att / "semantic" / "embeddings.npy", np.zeros((6, 3), "float32"))                         # tampered embeddings
    assert semantic.load_index(att, "m1") is None


def test_tiny_crops_are_skipped_and_missing_frames_are_tolerated(tmp_path):
    att, events, obs = synthetic_attempt(tmp_path)
    obs[0]["box"] = [0.5, 0.5, 0.51, 0.52]                                                             # about 3 px: too small to embed
    events.append({"event_key": "dddddddddddd", "track_ids": [9], "evidence": {"frames": [{"role": "mid", "t_ms": 1000, "missing": True}]}})
    meta = semantic.build_index(att, events, obs, FixtureEmbedder(), run_id="r", manifest_sha256="m")
    assert not any(i["kind"] == "crop" and i["event_key"] == "aaaaaaaaaaaa" for i in meta["items"]) and not any(i["event_key"] == "dddddddddddd" for i in meta["items"])


# ---------------- API ----------------
@pytest.fixture()
def sem_client(client, tmp_path):
    client.app.state.embedder = FixtureEmbedder()
    v = upload(client, tmp_path); run = make_run(client, v["id"]); assert run_with_fixture(client, run["id"]) == "completed"
    return client, run["id"]


def test_semantic_endpoints_contract_and_traceability(sem_client):
    c, rid = sem_client
    assert c.get(f"/api/runs/{rid}/semantic").json()["indexed"] is False
    built = c.post(f"/api/runs/{rid}/semantic/index").json(); assert built["indexed"] and built["items"] > 0 and built["model"]["source"] == "fixture"
    st = c.get(f"/api/runs/{rid}/semantic").json(); assert st["indexed"] and "not a probability" in st["score_meaning"]
    r = c.post(f"/api/runs/{rid}/search/semantic", json={"query": "something gray"}).json()
    assert r["source"] == "fixture" and not r["unsupported"] and len(r["results"]) == 1 and "not a confidence" in r["ordering"] + r["score_meaning"]
    hit = r["results"][0]; sem = hit["semantic"]
    assert sem["rank"] == 1 and isinstance(sem["similarity"], float) and "confidence" not in sem and sem["best_item"]["t_ms"] >= 0 and sem["model"] == "fixture-colour-embedder"
    assert c.get(sem["best_item"]["frame_url"]).status_code == 200                                      # the cited frame resolves
    assert hit["source"] == "fixture"                                                                   # fixture events stay tagged through retrieval


def test_structured_constraints_filter_before_ranking_and_intents_are_refused(sem_client):
    c, rid = sem_client
    none = c.post(f"/api/runs/{rid}/search/semantic", json={"query": "a person", "filters": {"class_name": "car"}}).json()
    assert none["structured_constraints_applied"]["classes"] == ["car"] and none["results"] == []               # the explicit filter wins over the text and leaves nothing to rank
    some = c.post(f"/api/runs/{rid}/search/semantic", json={"query": "a person", "filters": {"type": "zone_entry"}}).json()
    assert len(some["results"]) == 1 and some["candidates_after_structured_filter"] == 1
    bad = c.post(f"/api/runs/{rid}/search/semantic", json={"query": "unattended bag"}).json()
    assert bad["unsupported"] and bad["results"] == [] and any("Unattended" in n for n in bad["notices"])
    assert c.post(f"/api/runs/{rid}/search/semantic", json={"query": ""}).status_code == 422
    assert c.post(f"/api/runs/{rid}/search/semantic", json={"query": "x", "limit": 0}).status_code == 422


def test_semantic_is_optional_and_failures_never_break_the_core_app(client, tmp_path, monkeypatch):
    v = upload(client, tmp_path); run = make_run(client, v["id"]); run_with_fixture(client, run["id"])
    rid = run["id"]
    def unavailable():
        raise semantic.EmbedderUnavailable("The embedding model could not be loaded: offline")
    monkeypatch.setattr(semantic, "default_embedder", unavailable)
    r = client.post(f"/api/runs/{rid}/search/semantic", json={"query": "person"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "semantic_unavailable" and "Structured search still works" in r.json()["error"]["message"]
    assert client.post(f"/api/runs/{rid}/search", json={"query": "person entering"}).status_code == 200      # structured search unaffected
    assert client.get(f"/api/runs/{rid}/events").status_code == 200 and client.get(f"/api/runs/{rid}/report").status_code == 200
    monkeypatch.setenv("VI_SEMANTIC", "off")
    assert client.post(f"/api/runs/{rid}/search/semantic", json={"query": "person"}).json()["error"]["code"] == "semantic_unavailable"
    assert client.get(f"/api/runs/{rid}/semantic").json()["enabled"] is False


def test_semantic_requires_a_completed_run(client, tmp_path):
    client.app.state.embedder = FixtureEmbedder()
    v = upload(client, tmp_path); run = make_run(client, v["id"])
    r = client.post(f"/api/runs/{run['id']}/search/semantic", json={"query": "person"}); assert r.status_code == 409
    assert client.post(f"/api/runs/{run['id']}/semantic/index").status_code == 409
    assert client.post("/api/runs/nope/search/semantic", json={"query": "x"}).status_code == 404


def test_the_index_does_not_alter_the_published_artifacts(sem_client, data_dir):
    c, rid = sem_client
    from video_investigator.reports.verify import verify_attempt
    attempt = next((data_dir / "runs" / rid).glob("attempt-*"))
    before = (attempt / "manifest.json").read_bytes()
    c.post(f"/api/runs/{rid}/semantic/index")
    assert (attempt / "manifest.json").read_bytes() == before and verify_attempt(attempt) == []          # derived data lives beside, not inside, the manifest
