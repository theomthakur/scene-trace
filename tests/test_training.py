"""Fine-tuning path tests. They run offline on a randomly initialised model and synthetic images: they prove the pipeline works (metrics, deterministic split,
loss, frozen backbone, checkpoint round-trip, opt-in loading). They say nothing about accuracy; the real comparison is in docs/evidence/finetune-*.json."""
import json
from pathlib import Path
import numpy as np
import pytest
import torch
from video_investigator.training import data, finetune
from video_investigator.training.metrics import average_precision, bootstrap_difference

REPO = Path(__file__).resolve().parent.parent
B = lambda *xs: np.array(xs, float).reshape(-1, 4)


# ---------------- metrics ----------------
def test_ap_perfect_missed_duplicate_and_false_positive():
    gt = [B(0, 0, 10, 10), B(0, 0, 10, 10, 20, 20, 30, 30)]
    perfect = [(B(0, 0, 10, 10), np.array([0.9])), (B(0, 0, 10, 10, 20, 20, 30, 30), np.array([0.8, 0.7]))]
    assert average_precision(perfect, gt)["ap"] == pytest.approx(1.0)
    missed = [(B(0, 0, 10, 10), np.array([0.9])), (B(0, 0, 10, 10), np.array([0.8]))]                  # 2 of 3 found
    assert average_precision(missed, gt)["ap"] == pytest.approx(2 / 3)
    dup = [(B(0, 0, 10, 10, 0, 0, 10, 10), np.array([0.9, 0.8])), (B(0, 0, 10, 10, 20, 20, 30, 30), np.array([0.7, 0.6]))]
    r = average_precision(dup, gt)                                                                       # the second box on the same truth is a false positive
    assert r["ap"] < 1.0 and r["n_pred"] == 4
    fp_first = [(B(100, 100, 110, 110, 0, 0, 10, 10), np.array([0.95, 0.9])), (B(0, 0, 10, 10, 20, 20, 30, 30), np.array([0.8, 0.7]))]
    assert average_precision(fp_first, gt)["ap"] < average_precision(perfect, gt)["ap"]                  # a confident wrong box costs precision


def test_ap_threshold_equality_empty_truth_and_empty_predictions():
    gt = [B(0, 0, 10, 10)]
    half = [(B(0, 0, 10, 5), np.array([0.9]))]                                                            # IoU exactly 0.5
    assert average_precision(half, gt, 0.5)["ap"] == pytest.approx(1.0) and average_precision(half, gt, 0.51)["ap"] == 0.0
    assert average_precision([(B(), np.array([]))], gt)["ap"] == 0.0
    none = average_precision([(B(0, 0, 5, 5), np.array([0.9]))], [B()])
    assert none["ap"] is None and none["n_gt"] == 0                                                       # undefined, never a perfect score


def test_bootstrap_difference_is_reproducible_and_signed():
    rng = np.random.default_rng(0)
    gts = [B(0, 0, 10, 10) for _ in range(40)]
    good = [(B(0, 0, 10, 10), np.array([0.9])) for _ in gts]
    bad = [(B(50, 50, 60, 60), np.array([0.9])) for _ in gts]
    a = bootstrap_difference(good, bad, gts, n_boot=100, seed=3); b = bootstrap_difference(good, bad, gts, n_boot=100, seed=3)
    assert a == b and a["low"] > 0.9 and a["resamples"] == 100
    assert bootstrap_difference(good, good, gts, n_boot=50)["high"] == 0.0 and rng is not None


# ---------------- deterministic split ----------------
def synthetic_items(n=60):
    return [data.Item(f"data/img{i}.png", 64, 64, [[8, 8, 32, 32]], [1 + i % 3]) for i in range(n)]


def test_split_is_deterministic_disjoint_and_independent_of_input_order():
    items = synthetic_items(); sizes = {"train": 30, "val": 10, "test": 20}
    a = data.make_split(items, sizes); b = data.make_split(list(reversed(items)), sizes)
    assert {k: [i.file for i in v] for k, v in a.items()} == {k: [i.file for i in v] for k, v in b.items()}
    files = [i.file for v in a.values() for i in v]
    assert len(files) == len(set(files)) == 60 and {k: len(v) for k, v in a.items()} == sizes


def test_committed_split_manifest_is_self_consistent():
    import hashlib
    m = json.loads((REPO / "fixtures" / "finetune" / "split_manifest.json").read_text())
    assert m["declared_license"] == "cc0-1.0" and m["classes"] == data.CLASSES
    assert hashlib.sha256(json.dumps(m["files"], sort_keys=True).encode()).hexdigest() == m["files_sha256"]
    sets = {k: set(v) for k, v in m["files"].items()}
    assert not (sets["train"] & sets["val"] or sets["train"] & sets["test"] or sets["val"] & sets["test"])
    assert {k: len(v) for k, v in sets.items()} == {"train": 1000, "val": 200, "test": 800}


# ---------------- the training path on a random-initialised model ----------------
class TinyDS:
    def __init__(self, n=8):
        g = torch.Generator().manual_seed(1); self.items = []; self.imgs = []
        for i in range(n):
            img = torch.rand(3, 96, 96, generator=g) * 0.2
            x1, y1 = 10 + (i % 3) * 8, 12 + (i % 2) * 10; img[:, y1:y1 + 40, x1:x1 + 30] = 0.9                        # a bright rectangle is the object
            self.imgs.append(img); self.items.append(data.Item(f"synthetic{i}", 96, 96, [[x1, y1, x1 + 30, y1 + 40]], [3]))
    def __len__(self): return len(self.items)
    def __getitem__(self, i):
        it = self.items[i]; return self.imgs[i], {"boxes": torch.tensor(it.boxes, dtype=torch.float32), "labels": torch.tensor(it.labels), "image_id": i}


def test_training_loop_updates_only_trainable_parameters_and_saves_a_loadable_checkpoint(tmp_path):
    torch.manual_seed(0); model = finetune.build_model(pretrained_coco=False, freeze_backbone=True)
    heads_before = {n: p.detach().clone() for n, p in model.named_parameters() if p.requires_grad}
    res = finetune.train(model, TinyDS(8), TinyDS(4), epochs=2, batch=4, lr=0.01, momentum=0.9, weight_decay=5e-4, seed=1, score_thresh=0.05, iou_thr=0.5, out_dir=tmp_path, log=lambda *_: None)
    assert res["steps"] == 4 and res["frozen_params_unchanged"] is True and len(res["history"]) == 2
    assert all(np.isfinite(h["train_loss"]) for h in res["history"])
    assert any(not torch.equal(heads_before[n], p) for n, p in model.named_parameters() if n in heads_before)        # the heads did learn something
    assert (tmp_path / "checkpoint.pt").is_file() and len(res["best"]["sha256"]) == 64
    reloaded, ck = finetune.load_checkpoint(tmp_path / "checkpoint.pt")
    assert ck["classes"] == data.CLASSES and ck["num_classes"] == 4 and ck["base_weights"] == "COCO_V1"
    x = TinyDS(2)[0][0]
    best_state = ck["state_dict"]
    assert set(best_state) == set(reloaded.state_dict())
    with torch.inference_mode():
        a = reloaded.eval()([x])[0]["boxes"]; b = finetune.load_checkpoint(tmp_path / "checkpoint.pt")[0]([x])[0]["boxes"]
    assert torch.equal(a, b)                                                                                           # loading is deterministic


def test_predict_and_per_class_ap_run_end_to_end_and_baseline_maps_only_person(tmp_path):
    ds = TinyDS(4); torch.manual_seed(0); model = finetune.build_model(pretrained_coco=False)
    preds = finetune.predict(model, ds, score_thresh=0.0)
    assert len(preds) == 4 and all(len(p[0]) == len(p[1]) == len(p[2]) for p in preds)
    res = finetune.per_class_ap(preds, ds)
    assert set(res) == set(data.CLASSES) and res["helmet"]["ap"] is None and res["person"]["n_gt"] == 4         # no helmet truth in this set: undefined, not zero
    assert 0.0 <= finetune.mean_ap(res) <= 1.0


def test_warm_start_copies_the_coco_person_row_into_the_person_slot_only(monkeypatch):
    """build_model(pretrained_coco=True) copies COCO background (0) and person (label 1) into slots 0 and person; helmet and head start fresh. Uses a stand-in donor (no download)."""
    from torchvision.models.detection import fasterrcnn_mobilenet_v3_large_320_fpn
    torch.manual_seed(3)
    donor = fasterrcnn_mobilenet_v3_large_320_fpn(weights=None, weights_backbone=None, num_classes=91)
    old = donor.roi_heads.box_predictor
    snap = {"cls_w": old.cls_score.weight.detach().clone(), "cls_b": old.cls_score.bias.detach().clone(), "box_w": old.bbox_pred.weight.detach().clone(), "box_b": old.bbox_pred.bias.detach().clone()}
    monkeypatch.setattr(finetune, "fasterrcnn_mobilenet_v3_large_320_fpn", lambda **k: donor)
    m = finetune.build_model(pretrained_coco=True); new = m.roi_heads.box_predictor; person = data.CLASSES.index("person") + 1
    assert new.cls_score.out_features == 4 and new.bbox_pred.out_features == 16
    assert torch.equal(new.cls_score.weight[person], snap["cls_w"][1]) and torch.equal(new.cls_score.bias[person], snap["cls_b"][1])
    assert torch.equal(new.bbox_pred.weight[4 * person:4 * person + 4], snap["box_w"][4:8]) and torch.equal(new.bbox_pred.bias[4 * person:4 * person + 4], snap["box_b"][4:8])
    assert torch.equal(new.cls_score.weight[0], snap["cls_w"][0]) and torch.equal(new.bbox_pred.weight[0:4], snap["box_w"][0:4])
    helmet = data.CLASSES.index("helmet") + 1
    assert not torch.equal(new.cls_score.weight[helmet], snap["cls_w"][1])                      # a new class is not a copy of person
    assert all(not p.requires_grad for p in m.backbone.parameters()) and all(p.requires_grad for p in m.roi_heads.parameters())


def test_detector_loads_an_opt_in_checkpoint_and_records_it_without_touching_the_config_hash(tmp_path, monkeypatch):
    from video_investigator.config import load_settings
    from video_investigator.vision.detector import Detector, DetectorError
    base_hash = load_settings().config_hash()
    model = finetune.build_model(pretrained_coco=False); sha = finetune.save_checkpoint(model, tmp_path / "ck.pt", {"epoch": 1})
    monkeypatch.setenv("VI_DETECTOR_CHECKPOINT", str(tmp_path / "ck.pt"))
    s = load_settings(overrides={"detector": {"classes": ["person", "helmet", "head"]}})
    d = Detector(s); info = d.info()
    assert info["weights"].startswith("fine-tuned") and info["weights_sha256"] == sha and info["base_weights"] == "COCO_V1" and info["supported_classes"] == ["helmet", "head", "person"]
    assert load_settings().config_hash() == base_hash                                                                   # the checkpoint is not part of the config hash
    monkeypatch.setenv("VI_DETECTOR_CHECKPOINT", str(tmp_path / "missing.pt"))
    with pytest.raises(DetectorError) as e:
        Detector(s)
    assert e.value.code == "checkpoint_unavailable"                                                                     # a bad checkpoint fails loudly, never falls back silently


def test_the_held_out_test_split_refuses_a_second_evaluation(tmp_path, monkeypatch):
    done = tmp_path / "t.json"; done.write_text("{}"); monkeypatch.setattr(finetune, "TEST_RESULT", done)
    with pytest.raises(SystemExit) as e:
        finetune.cmd_evaluate(type("A", (), {"include_test": True, "name": "x"})())
    assert "already evaluated" in str(e.value)
