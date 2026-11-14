"""Explanation workflow tests. The explainer is a scripted double tagged source='fixture': these tests check grounding, storage, flags, redaction and failure
behaviour. They say nothing about how good a real model's descriptions are; that is measured in docs/evidence/explanation-eval.json."""
import pytest
from test_api_flow import make_run, run_with_fixture, upload
from video_investigator.explain import vlm


class FixtureExplainer:
    name, revision, source = "fixture-explainer", "0", "fixture"
    def __init__(self, text="A person standing in a grey scene wearing dark clothes, partly out of focus."):
        self.text, self.calls = text, []
    def generate(self, images, prompt):
        self.calls.append((len(images), prompt)); return self.text


@pytest.fixture()
def ex_client(client, tmp_path):
    ex = FixtureExplainer(); client.app.state.explainer = ex
    v = upload(client, tmp_path); run = make_run(client, v["id"]); assert run_with_fixture(client, run["id"]) == "completed"
    event = client.get(f"/api/runs/{run['id']}/events").json()["events"][0]
    return client, run["id"], event, ex


def test_explanation_is_grounded_stored_labelled_and_reproducible(ex_client):
    c, rid, e, ex = ex_client
    r = c.post(f"/api/events/{e['id']}/explain", json={})
    assert r.status_code == 201
    x = r.json()
    assert x["model"] == {"name": "fixture-explainer", "revision": "0", "source": "fixture"} and "unverified" in x["disclaimer"] and len(x["prompt_sha256"]) == 64
    assert len(x["frames"]) == 1 and x["frames"][0]["role"] == "mid" and x["frames"][0]["kind"] in ("crop", "frame") and c.get(x["frames"][0]["frame_url"]).status_code == 200
    assert ex.calls[0][0] == 1 and "Describe this person" in ex.calls[0][1] and "track" not in ex.calls[0][1].lower()       # the model gets pixels and a neutral question only
    again = c.post(f"/api/events/{e['id']}/explain", json={}).json()
    assert again["prompt_sha256"] == x["prompt_sha256"] and again["id"] != x["id"]                                          # same prompt, a new record
    listed = c.get(f"/api/events/{e['id']}/explanations").json()
    assert [y["id"] for y in listed["explanations"]] == [again["id"], x["id"]] and "unverified" in listed["disclaimer"]


def test_explanations_never_change_events_reviews_or_reports(ex_client):
    c, rid, e, _ = ex_client
    before = (c.get(f"/api/runs/{rid}/events").json(), c.get(f"/api/runs/{rid}/report?format=markdown").text.split("Generated")[0])
    c.post(f"/api/events/{e['id']}/explain", json={"frames": ["start", "mid", "end"]})
    after_events = c.get(f"/api/runs/{rid}/events").json()
    assert after_events["events"] == before[0]["events"] and after_events["total"] == before[0]["total"]
    assert c.get(f"/api/runs/{rid}/report?format=markdown").text.split("Generated")[0] == before[1]


def test_multiple_frames_are_allowed_but_flagged_as_less_reliable(ex_client):
    c, rid, e, ex = ex_client
    x = c.post(f"/api/events/{e['id']}/explain", json={"frames": ["start", "end"]}).json()
    assert len(x["frames"]) == 2 and ex.calls[-1][0] == 2 and "images of the same person" in ex.calls[-1][1]
    assert any(f.startswith("multi_image_input") for f in x["flags"]) and x["status"] == "flagged"
    assert c.post(f"/api/events/{e['id']}/explain", json={"frames": ["middle"]}).status_code == 422
    assert c.post(f"/api/events/{e['id']}/explain", json={"frames": []}).status_code == 422


def test_automatic_checks_flag_unsupported_claims(ex_client):
    event = {"type": "zone_entry", "class_name": "person", "start_ms": 1000, "end_ms": 3000}
    f = lambda text, det={"person"}: vlm.check_text(text, event, det)
    assert any("unsupported_inference_words" in x and "suspicious" in x for x in f("A suspicious person standing by the door looking around the area."))
    assert any("intends" in x for x in f("The person intends to leave through the back entrance of the shop."))
    assert not any("unsupported_inference_words" in x for x in f("A man who is wearing a grey jacket and carrying a small bag."))        # 'who' alone is ordinary English
    assert any("time_outside_evidence" in x for x in f("At 40 seconds the person leaves the frame and walks away from the shop."))
    assert not any("time_outside_evidence" in x for x in f("At 2 s the person stands near a doorway wearing dark clothes today."))
    assert any("mentions_object_not_in_detections: bicycle" in x for x in f("A person next to a bicycle wearing dark clothes in the street."))
    assert not any("mentions_object_not_in_detections" in x for x in f("A person next to a bicycle wearing dark clothes in the street.", {"person", "bicycle"}))
    assert any(x.startswith("uninformative") for x in f("A tracked person at 2.0 s."))
    assert any(x.startswith("degenerate_output") for x in f("Person #123456. Person #23456."))
    assert f("A person with short dark hair wearing a grey jacket and blue jeans, walking.") == []


def test_identifiers_are_redacted_before_storage_and_flagged(ex_client):
    c, rid, e, ex = ex_client
    ex.text = "The red car has a license plate which reads M-KC 1602 and a sticker."
    x = c.post(f"/api/events/{e['id']}/explain", json={}).json()
    assert "1602" not in x["text"] and "[redacted]" in x["text"] and any(f.startswith("identifier_redacted") for f in x["flags"]) and x["status"] == "flagged"
    assert "1602" not in str(c.get(f"/api/events/{e['id']}/explanations").json())


def test_explanations_are_optional_and_failure_never_breaks_the_core_app(client, tmp_path, monkeypatch):
    v = upload(client, tmp_path); run = make_run(client, v["id"]); run_with_fixture(client, run["id"])
    e = client.get(f"/api/runs/{run['id']}/events").json()["events"][0]
    def gone():
        raise vlm.ExplainerUnavailable("The explanation model could not be loaded: offline.")
    monkeypatch.setattr(vlm, "default_explainer", gone)
    r = client.post(f"/api/events/{e['id']}/explain", json={})
    assert r.status_code == 503 and r.json()["error"]["code"] == "explainer_unavailable" and "Everything else works" in r.json()["error"]["message"]
    assert client.get(f"/api/events/{e['id']}/explanations").json()["explanations"] == []
    for url in (f"/api/runs/{run['id']}/events", f"/api/runs/{run['id']}/report", f"/api/runs/{run['id']}/observations"):
        assert client.get(url).status_code == 200
    assert client.put(f"/api/events/{e['id']}/review", json={"verdict": "confirmed", "note": "", "expected_version": 0}).status_code == 200
    monkeypatch.setenv("VI_EXPLAIN", "off")
    assert client.post(f"/api/events/{e['id']}/explain", json={}).json()["error"]["code"] == "explainer_unavailable"
    st = client.get("/api/explainer").json(); assert st["enabled"] is False and st["model"]["license"] == "apache-2.0" and "unverified" in st["disclaimer"]


def test_requires_a_completed_run_and_an_existing_event(client, tmp_path):
    client.app.state.explainer = FixtureExplainer()
    assert client.post("/api/events/nope/explain", json={}).status_code == 404
    assert client.get("/api/events/nope/explanations").status_code == 404


def test_migration_creates_the_explanations_table_on_an_existing_v1_database(tmp_path):
    from sqlalchemy import text
    from video_investigator.db.session import make_engine, migrate
    eng = make_engine(tmp_path / "old.db")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")); c.execute(text("INSERT INTO schema_migrations VALUES (1, 'x')"))
    from video_investigator.db.models import Base
    with eng.begin() as c:
        for t in Base.metadata.sorted_tables:
            if t.name != "explanations": t.create(c, checkfirst=True)
    assert migrate(eng) == 2
    with eng.connect() as c:
        assert c.execute(text("SELECT name FROM sqlite_master WHERE name='explanations'")).scalar() == "explanations"
