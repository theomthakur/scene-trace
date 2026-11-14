"""Cross-camera association tests: gating, one-to-one assignment, ambiguity rejection, evaluation maths, and behaviour on synthetic scenarios.
Everything here is synthetic or logic-level; real-footage negative controls are in docs/evidence/crosscam-eval.json."""
import numpy as np
import pytest
from video_investigator.crosscam.associate import LABEL, Association, Params, Tracklet, associate, chain_identity_switches, evaluate, gate
from video_investigator.evaluation.crosscam_fixtures import scenario


def tl(cam, tid, start, end, vec, cls="person", ident=None):
    v = np.asarray(vec, float); return Tracklet(cam, tid, cls, start, end, v / np.linalg.norm(v), ident)


def test_gating_rules():
    p = Params(min_gap_s=1, max_gap_s=30)
    a = tl("A", 1, 0, 10, [1, 0])
    assert gate(a, tl("B", 1, 15, 20, [1, 0]), p)
    assert not gate(a, tl("A", 2, 15, 20, [1, 0]), p)                      # same camera
    assert not gate(a, tl("B", 1, 15, 20, [1, 0], cls="car"), p)           # different class
    assert not gate(a, tl("B", 1, 5, 20, [1, 0]), p)                       # starts before A ends
    assert not gate(a, tl("B", 1, 10.5, 20, [1, 0]), p)                    # gap below the minimum
    assert not gate(a, tl("B", 1, 100, 110, [1, 0]), p)                    # gap above the maximum
    assert gate(a, tl("B", 1, 11, 20, [1, 0]), p) and gate(a, tl("B", 1, 40, 50, [1, 0]), p)    # gap equal to either limit is allowed


def test_clear_match_is_proposed_with_its_similarity_margin_and_label():
    a = [tl("A", 1, 0, 10, [1, 0, 0]), tl("A", 2, 0, 10, [0, 1, 0])]; b = [tl("B", 1, 20, 30, [0.99, 0.05, 0]), tl("B", 2, 20, 30, [0.02, 1, 0.01])]
    r = associate(a, b, Params(threshold=0.8))
    assert [(x.a.track_id, x.b.track_id) for x in r] == [(1, 1), (2, 2)] or [(x.a.track_id, x.b.track_id) for x in r] == [(2, 2), (1, 1)]
    assert all(x.note == LABEL and x.similarity > 0.95 and x.margin > 0.5 and x.gap_s == 10 for x in r) and "Not an identification" in LABEL


def test_ambiguous_matches_are_rejected_not_guessed_and_one_to_one_holds():
    a = [tl("A", 1, 0, 10, [1, 0])]; b = [tl("B", 1, 20, 30, [1, 0.01]), tl("B", 2, 20, 30, [1, -0.01])]       # two nearly identical candidates
    assert associate(a, b, Params(threshold=0.5, margin=0.05)) == []
    assert len(associate(a, b, Params(threshold=0.5, margin=0.0))) == 1                                         # margin 0 would accept a coin flip
    two_a = [tl("A", 1, 0, 10, [1, 0]), tl("A", 2, 0, 10, [1, 0.3])]; one_b = [tl("B", 1, 20, 30, [1, 0.1])]
    assert len(associate(two_a, one_b, Params(threshold=0.5, margin=0.0))) == 1                                 # a B track is used at most once


def test_threshold_and_empty_inputs():
    a = [tl("A", 1, 0, 10, [1, 0])]; b = [tl("B", 1, 20, 30, [0.6, 0.8])]                                       # similarity 0.6
    assert associate(a, b, Params(threshold=0.7)) == [] and len(associate(a, b, Params(threshold=0.6, margin=0))) == 1
    assert associate([], b) == [] and associate(a, []) == []
    assert associate(a, [tl("B", 1, 2, 3, [1, 0])]) == []                                                       # nothing is gate-feasible


def test_associator_never_reads_ground_truth_identity():
    A, B, _ = scenario(n_ids=20, noise=0.4, seed=5); p = Params(threshold=0.6, margin=0.02)
    base = [(x.a.key, x.b.key) for x in associate(A, B, p)]
    for t in A + B:
        t.identity = "scrambled"
    assert [(x.a.key, x.b.key) for x in associate(A, B, p)] == base


def test_evaluation_counts_and_chain_identity_switches():
    a1, a2 = tl("A", 1, 0, 5, [1, 0], ident="x"), tl("A", 2, 0, 5, [0, 1], ident="y"); b1, b2 = tl("B", 1, 9, 12, [1, 0], ident="x"), tl("B", 2, 9, 12, [0, 1], ident="z")
    r = [Association(a1, b1, .9, .5, 4), Association(a2, b2, .9, .5, 4)]
    ev = evaluate(r, [a1, a2], [b1, b2])
    assert ev["proposed"] == 2 and ev["correct"] == 1 and ev["wrong"] == 1 and ev["wrong_association_rate"] == 0.5 and ev["true_pairs"] == 1 and ev["recall"] == 1.0
    assert evaluate([], [a1], [b1])["wrong_association_rate"] is None                                            # undefined, not zero
    c1 = tl("C", 1, 20, 25, [1, 0], ident="x"); c2 = tl("C", 2, 20, 25, [0, 1], ident="y")
    sw = chain_identity_switches(r, [Association(b1, c1, .9, .5, 8), Association(b2, c2, .9, .5, 8)])
    assert sw == {"chains": 2, "identity_switches": 1}


def test_synthetic_scenarios_degrade_with_noise_and_are_deterministic():
    p = Params(threshold=0.5, margin=0.02, max_gap_s=60)
    def run(noise, seed=1):
        A, B, C = scenario(n_ids=40, noise=noise, seed=seed); ab = associate(A, B, p); return evaluate(ab, A, B)
    clean, noisy = run(0.2), run(4.0)
    assert clean["wrong_association_rate"] is not None and clean["wrong_association_rate"] <= 0.1 and clean["recall"] >= 0.5
    assert noisy["wrong_association_rate"] is None or noisy["wrong_association_rate"] >= clean["wrong_association_rate"]      # distinctive appearance matters
    assert run(0.5) == run(0.5)
    A, B, _ = scenario(n_ids=40, noise=0.5, seed=1); assert all(t.class_name == "person" for t in A + B)


# ---------------- API ----------------
def test_crosscam_endpoint_requires_two_runs_an_offset_and_returns_labelled_candidates(client, tmp_path, monkeypatch):
    monkeypatch.setenv("VI_EXPERIMENTAL_CROSSCAM", "on")
    from helpers import make_video
    from test_api_flow import make_run, run_with_fixture, upload
    from test_semantic import FixtureEmbedder
    client.app.state.embedder = FixtureEmbedder()
    ids = []
    for name in ("a.mp4", "b.mp4"):
        v = upload(client, tmp_path, name=name); run = make_run(client, v["id"]); assert run_with_fixture(client, run["id"], owner=name) == "completed"; ids.append(run["id"])
    ok = client.post("/api/crosscam/associate", json={"run_a": ids[0], "run_b": ids[1], "offset_b_s": 30, "threshold": 0.5, "margin": 0.0})
    assert ok.status_code == 200
    body = ok.json()
    assert body["tracks_considered"] == {"run_a": 1, "run_b": 1} and body["descriptor_model"]["source"] == "fixture" and "Not an identification" in body["label"]
    assert any("not been measured" in w for w in body["warnings"]) and any("hint" in w for w in body["warnings"])
    assert len(body["associations"]) == 1 and body["associations"][0]["note"] == body["label"] and body["associations"][0]["from"]["run_id"] == ids[0] and body["associations"][0]["gap_s"] > 0
    assert client.post("/api/crosscam/associate", json={"run_a": ids[0], "run_b": ids[1], "offset_b_s": 0.0, "threshold": 0.5, "margin": 0.0}).json()["associations"] == []                      # simultaneous tracks cannot be a hand-off between cameras
    assert client.post("/api/crosscam/associate", json={"run_a": ids[0], "run_b": ids[1]}).status_code == 422            # no offset: the platform never guesses camera timing
    assert client.post("/api/crosscam/associate", json={"run_a": ids[0], "run_b": ids[0], "offset_b_s": 5}).json()["error"]["code"] == "same_run"
    assert client.post("/api/crosscam/associate", json={"run_a": ids[0], "run_b": "nope", "offset_b_s": 5}).status_code == 404
    assert client.post("/api/crosscam/associate", json={"run_a": ids[0], "run_b": ids[1], "offset_b_s": 30, "class_name": "car"}).json()["tracks_considered"] == {"run_a": 0, "run_b": 0}


def test_crosscam_is_off_by_default_because_it_is_unvalidated(client):
    r = client.post("/api/crosscam/associate", json={"run_a": "a", "run_b": "b", "offset_b_s": 5})
    assert r.status_code == 404 and r.json()["error"]["code"] == "experimental_disabled" and "unvalidated" in r.json()["error"]["message"]
