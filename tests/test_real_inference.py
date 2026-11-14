"""Real-inference smoke tests: the pretrained COCO detector on real decoded footage. Excluded from the default run (offline, fast):
    pytest -m real_inference
Needs the weights (downloaded on first use) and the demo clips (python scripts/fetch_demo_media.py)."""
import hashlib, json
from pathlib import Path
import pytest
from video_investigator.config import load_settings
from video_investigator.events.rules import Zone
from video_investigator.reports.verify import verify_attempt
from video_investigator.runner import process_video, zones_from_dicts

CLIP = Path(__file__).resolve().parent.parent / "var" / "candidates" / "pedestrian_area.webm"
ZONES = Path(__file__).resolve().parent.parent / "fixtures" / "benchmark" / "zones_pedestrian_area.json"
WEIGHTS_SHA256 = "907ea3f91ff92242bc1baea8049276a3e76bca48ce7560bd268cc029f37977b5"
pytestmark = [pytest.mark.real_inference, pytest.mark.skipif(not CLIP.exists(), reason="demo clip missing: python scripts/fetch_demo_media.py")]


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    zones = zones_from_dicts(json.loads(ZONES.read_text()))
    return process_video(CLIP, zones, load_settings(), tmp_path_factory.mktemp("runs"), max_frames=40)


def test_real_weights_real_pixels_real_detections(result):
    meta = result["run_meta"]
    assert meta["detector"]["weights_sha256"] == WEIGHTS_SHA256 and meta["detector"]["name"] == "fasterrcnn_mobilenet_v3_large_320_fpn"
    obs = result["observations"]
    assert len(obs) > 100 and {o["source"] for o in obs} == {"detector"}
    assert {o["class_name"] for o in obs} <= set(load_settings().detector.classes) and sum(o["class_name"] == "person" for o in obs) > 80
    assert meta["data_source"].startswith("detector") and meta["timings"]["sampled_frames"] == 40


def test_timestamps_and_coordinates_are_valid(result):
    ts = sorted({o["t_ms"] for o in result["observations"]})
    assert ts[0] == 0 and all(b - a in range(190, 215) for a, b in zip(ts, ts[1:]))           # 5 fps sampling by presentation time
    assert all(0 <= o["box"][0] < o["box"][2] <= 1 and 0 <= o["box"][1] < o["box"][3] <= 1 for o in result["observations"])
    assert result["run_meta"]["processed_frame_size"] == [960, 540] and result["run_meta"]["video"]["width"] == 1920


def test_run_is_deterministic_on_the_same_machine(result, tmp_path):
    again = process_video(CLIP, zones_from_dicts(json.loads(ZONES.read_text())), load_settings(), tmp_path, max_frames=40, make_clips=False)
    key = lambda r: hashlib.sha256(json.dumps([[o["t_ms"], o["track_id"], o["class_name"], o["box"]] for o in r["observations"]]).encode()).hexdigest()
    assert key(again) == key(result)


def test_published_attempt_is_internally_consistent_and_the_original_is_untouched(result):
    assert verify_attempt(result["attempt_dir"]) == []
    assert hashlib.sha1(CLIP.read_bytes()).hexdigest() == "51e89a672896e45cca17aa46cd223630a6266e26"


# ---------------- semantic embeddings (real model) ----------------
def test_real_clip_embeddings_are_normalised_and_separate_obvious_colours():
    import numpy as np
    from PIL import Image
    from video_investigator.search import semantic
    e = semantic.ClipEmbedder()
    img = e.embed_images([Image.new("RGB", (224, 224), (220, 20, 20)), Image.new("RGB", (224, 224), (20, 20, 220))])
    txt = e.embed_texts(["a red square", "a blue square"])
    assert img.shape == (2, 512) and txt.shape == (2, 512) and np.allclose(np.linalg.norm(img, axis=1), 1, atol=1e-4)
    sims = txt @ img.T
    assert sims[0, 0] > sims[0, 1] and sims[1, 1] > sims[1, 0]          # each colour word is closer to its own colour
