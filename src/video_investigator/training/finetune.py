"""Reproducible fine-tuning of the detector's heads on licensed labelled data, and a held-out comparison with the pretrained baseline.

    python -m video_investigator.training.finetune prepare            deterministic split + download the needed images
    python -m video_investigator.training.finetune train              fine-tune (selection by validation AP50); writes var/models/<name>/
    python -m video_investigator.training.finetune freeze             record checkpoint and split hashes BEFORE the test split is touched
    python -m video_investigator.training.finetune evaluate [--include-test]   development report; the test split can be evaluated once

Design: start from the COCO-pretrained Faster R-CNN MobileNetV3-Large 320 FPN, replace the box predictor with helmet / head / person classes (the person row is warm-started from COCO's
person row), freeze the backbone, train the RPN and ROI heads with SGD. The baseline is the unmodified pretrained model; it can only ever say "person", so helmet and head are
reported for the fine-tuned model only. One training seed: no run-to-run variance is estimated.
"""
from __future__ import annotations
import argparse, hashlib, json, platform, subprocess, sys, time
from pathlib import Path
import numpy as np
import torch
from torchvision.models.detection import FasterRCNN_MobileNet_V3_Large_320_FPN_Weights, fasterrcnn_mobilenet_v3_large_320_fpn
from torchvision.models.detection.faster_rcnn import FastRCNNPredictor
from ..config import REPO
from . import data
from .metrics import average_precision, bootstrap_difference

CLASSES = data.CLASSES
NUM_CLASSES = len(CLASSES) + 1
MODELS = REPO / "var" / "models"
EVIDENCE = REPO / "docs" / "evidence"
FREEZE = REPO / "fixtures" / "finetune" / "FREEZE.json"
TEST_RESULT = EVIDENCE / "finetune-test-results.json"
DEFAULTS = {"epochs": 6, "batch": 8, "lr": 0.01, "momentum": 0.9, "weight_decay": 5e-4, "seed": 7, "freeze_backbone": True, "score_thresh": 0.05, "iou_thr": 0.5, "image_size": 320}


def set_image_size(model, size: int | None):
    """The detector rescales images internally (320 for this variant). The dataset images are 416 px with small helmets, so native resolution can help."""
    if size:
        model.transform.min_size = (size,); model.transform.max_size = size
    return model


def build_model(pretrained_coco: bool = True, freeze_backbone: bool = True, image_size: int | None = None):
    """pretrained_coco=False builds the same architecture with random weights (used by offline tests; no download)."""
    if pretrained_coco:
        model = fasterrcnn_mobilenet_v3_large_320_fpn(weights=FasterRCNN_MobileNet_V3_Large_320_FPN_Weights.COCO_V1, weights_backbone=None)
        old = model.roi_heads.box_predictor; new = FastRCNNPredictor(old.cls_score.in_features, NUM_CLASSES); person = CLASSES.index("person") + 1
        with torch.no_grad():                      # warm start: background row and COCO's person row (COCO label 1)
            new.cls_score.weight[0] = old.cls_score.weight[0]; new.cls_score.bias[0] = old.cls_score.bias[0]
            new.cls_score.weight[person] = old.cls_score.weight[1]; new.cls_score.bias[person] = old.cls_score.bias[1]
            new.bbox_pred.weight[0:4] = old.bbox_pred.weight[0:4]; new.bbox_pred.bias[0:4] = old.bbox_pred.bias[0:4]
            new.bbox_pred.weight[4 * person:4 * person + 4] = old.bbox_pred.weight[4:8]; new.bbox_pred.bias[4 * person:4 * person + 4] = old.bbox_pred.bias[4:8]
        model.roi_heads.box_predictor = new
    else:
        model = fasterrcnn_mobilenet_v3_large_320_fpn(weights=None, weights_backbone=None, num_classes=NUM_CLASSES)
    if freeze_backbone:
        for p in model.backbone.parameters():
            p.requires_grad = False
    return set_image_size(model, image_size)


def save_checkpoint(model, path: Path, meta: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"classes": CLASSES, "num_classes": NUM_CLASSES, "arch": "fasterrcnn_mobilenet_v3_large_320_fpn", "base_weights": "COCO_V1", "meta": meta, "state_dict": model.state_dict()}, path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_checkpoint(path: Path):
    ck = torch.load(path, map_location="cpu", weights_only=False)
    size = (ck.get("meta", {}).get("config") or {}).get("image_size") or ck.get("meta", {}).get("image_size")
    model = build_model(pretrained_coco=False, freeze_backbone=False, image_size=size); model.load_state_dict(ck["state_dict"]); return model.eval(), ck


def collate(batch):
    return tuple(zip(*batch))


@torch.inference_mode()
def predict(model, ds, *, coco_baseline: bool = False, score_thresh: float = 0.05, batch: int = 8):
    """Per-image (boxes, scores, labels) with labels in dataset ids. For the COCO baseline only COCO 'person' survives, mapped to the dataset person id."""
    model.eval(); model.roi_heads.score_thresh = score_thresh; out = []; person = CLASSES.index("person") + 1
    for i in range(0, len(ds), batch):
        imgs = [ds[j][0] for j in range(i, min(len(ds), i + batch))]
        for r in model(imgs):
            b, s, l = r["boxes"].numpy(), r["scores"].numpy(), r["labels"].numpy()
            if coco_baseline:
                keep = l == 1; b, s, l = b[keep], s[keep], np.full(int(keep.sum()), person)
            out.append((b, s, l))
    return out


def per_class_ap(preds, ds, iou_thr: float = 0.5, classes=None) -> dict:
    res = {}
    for c in (classes or CLASSES):
        cid = CLASSES.index(c) + 1
        gts = [np.array([b for b, l in zip(it.boxes, it.labels) if l == cid], float).reshape(-1, 4) for it in ds.items]
        pc = [(p[0][p[2] == cid], p[1][p[2] == cid]) for p in preds]
        res[c] = average_precision(pc, gts, iou_thr)
    return res


def mean_ap(res: dict) -> float:
    v = [r["ap"] for r in res.values() if r["ap"] is not None]
    return float(np.mean(v)) if v else 0.0


def train(model, train_ds, val_ds, *, epochs, batch, lr, momentum, weight_decay, seed, score_thresh, iou_thr, out_dir: Path, log=print, max_steps: int | None = None) -> dict:
    torch.manual_seed(seed); g = torch.Generator().manual_seed(seed)
    loader = torch.utils.data.DataLoader(train_ds, batch_size=batch, shuffle=True, generator=g, collate_fn=collate)
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.SGD(params, lr=lr, momentum=momentum, weight_decay=weight_decay)
    total = epochs * len(loader); sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, total))
    history, best, step = [], {"val_map50": -1.0}, 0
    before = {n: p.detach().clone() for n, p in model.named_parameters() if not p.requires_grad}
    t0 = time.time()
    for epoch in range(1, epochs + 1):
        model.train(); losses = []
        for imgs, tgts in loader:
            loss_dict = model(list(imgs), [{"boxes": t["boxes"], "labels": t["labels"]} for t in tgts]); loss = sum(loss_dict.values())
            if not torch.isfinite(loss):
                raise FloatingPointError("Non-finite loss; stopping.")
            opt.zero_grad(); loss.backward(); opt.step(); sched.step(); losses.append(float(loss.detach())); step += 1
            if max_steps and step >= max_steps:
                break
        val = per_class_ap(predict(model, val_ds, score_thresh=score_thresh), val_ds, iou_thr)
        rec = {"epoch": epoch, "train_loss": round(float(np.mean(losses)), 4), "val_map50": round(mean_ap(val), 4), "val_ap50": {c: (None if r["ap"] is None else round(r["ap"], 4)) for c, r in val.items()}, "seconds": round(time.time() - t0, 1)}
        history.append(rec); log(json.dumps(rec))
        if rec["val_map50"] > best["val_map50"]:
            best = {**rec, "sha256": save_checkpoint(model, out_dir / "checkpoint.pt", {"epoch": epoch, "seed": seed, "image_size": getattr(model.transform, "max_size", None)})}
        if max_steps and step >= max_steps:
            break
    frozen_unchanged = all(torch.equal(before[n], p) for n, p in model.named_parameters() if n in before)
    return {"history": history, "best": best, "steps": step, "frozen_params_unchanged": frozen_unchanged, "train_seconds": round(time.time() - t0, 1)}


def git_commit() -> str:
    try:
        return subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    except Exception:
        return "unknown"


def datasets():
    items = data.load_items(); split = data.make_split(items); root = data.fetch_images(split)
    return {k: data.HardHatDataset(v, root) for k, v in split.items()}, split


def cmd_prepare(a):
    items = data.load_items(); split = data.make_split(items); man = data.write_manifest(split); data.fetch_images(split)
    print(json.dumps(man["summary"], indent=1)); return 0


def cmd_train(a):
    cfg = {**DEFAULTS, "epochs": a.epochs, "seed": a.seed, "lr": a.lr, "image_size": a.image_size, "freeze_backbone": not a.unfreeze_backbone}
    ds, split = datasets(); out = MODELS / a.name; out.mkdir(parents=True, exist_ok=True)
    model = build_model(True, cfg["freeze_backbone"], cfg["image_size"])
    res = train(model, ds["train"], ds["val"], epochs=cfg["epochs"], batch=cfg["batch"], lr=cfg["lr"], momentum=cfg["momentum"], weight_decay=cfg["weight_decay"], seed=cfg["seed"],
                score_thresh=cfg["score_thresh"], iou_thr=cfg["iou_thr"], out_dir=out)
    meta = {"config": cfg, "split_files_sha256": json.loads(data.MANIFEST.read_text())["files_sha256"],
            "hardware": f"{platform.machine()} {platform.platform()}, torch {torch.__version__}, device cpu", "code_commit": git_commit(), **res}
    (out / "training.json").write_text(json.dumps(meta, indent=2) + "\n"); print("best:", res["best"]); return 0


def cmd_freeze(a):
    out = MODELS / a.name; tr = json.loads((out / "training.json").read_text()); ck = (out / "checkpoint.pt")
    fr = {"frozen_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "checkpoint_sha256": hashlib.sha256(ck.read_bytes()).hexdigest(), "config": tr["config"], "split_files_sha256": tr["split_files_sha256"],
          "selected_epoch": tr["best"]["epoch"], "val_map50_at_selection": tr["best"]["val_map50"], "code_commit": git_commit(),
          "note": "Recorded after training and before the test split is evaluated. The test split is evaluated once; a second run is refused."}
    FREEZE.parent.mkdir(parents=True, exist_ok=True); FREEZE.write_text(json.dumps(fr, indent=2) + "\n"); print(json.dumps(fr, indent=2)); return 0


def cmd_evaluate(a):
    if a.include_test and TEST_RESULT.exists():
        raise SystemExit(f"The held-out test split was already evaluated ({TEST_RESULT}). It must not be re-run or tuned against.")
    ds, split = datasets(); model, ck = load_checkpoint(MODELS / a.name / "checkpoint.pt"); sha = hashlib.sha256((MODELS / a.name / "checkpoint.pt").read_bytes()).hexdigest()
    if a.include_test:
        fr = json.loads(FREEZE.read_text())
        if fr["checkpoint_sha256"] != sha:
            raise SystemExit("The checkpoint differs from the frozen one. Retrain and freeze again before evaluating the test split.")
    base = build_pretrained_baseline(); rep = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "checkpoint_sha256": sha, "code_commit": git_commit(), "splits": {}}
    tr = json.loads((MODELS / a.name / "training.json").read_text()); rep["training"] = {k: tr[k] for k in ("config", "best", "history", "train_seconds", "hardware", "frozen_params_unchanged")}
    for name in (["val", "test"] if a.include_test else ["val"]):
        d = ds[name]; ft = predict(model, d, score_thresh=DEFAULTS["score_thresh"]); bl = predict(base, d, coco_baseline=True, score_thresh=DEFAULTS["score_thresh"])
        ap_ft, ap_bl = per_class_ap(ft, d), per_class_ap(bl, d)
        pid = CLASSES.index("person") + 1
        gts = [np.array([b for b, l in zip(it.boxes, it.labels) if l == pid], float).reshape(-1, 4) for it in d.items]
        pf = [(p[0][p[2] == pid], p[1][p[2] == pid]) for p in ft]; pb = [(p[0][p[2] == pid], p[1][p[2] == pid]) for p in bl]
        rep["splits"][name] = {"images": len(d), "boxes": data.split_summary({name: d.items})[name]["boxes"],
                               "finetuned_ap50": {c: r for c, r in ap_ft.items()},
                               "pretrained_baseline_ap50": {c: ({**r, "note": None} if c == "person" else {"ap": None, "n_gt": r["n_gt"], "note": "not applicable: COCO has no such class, so the baseline cannot detect it"}) for c, r in ap_bl.items()},
                               "person_ap50_difference_finetuned_minus_baseline": {"value": (ap_ft["person"]["ap"] - ap_bl["person"]["ap"]) if ap_ft["person"]["ap"] is not None and ap_bl["person"]["ap"] is not None else None,
                                                                                  "bootstrap_95": bootstrap_difference(pf, pb, gts)}}
    rep["reading"] = ("One training seed, one split, CPU. helmet and head have no baseline because COCO lacks them, so a large gain there is expected by construction and is not evidence of a better detector. "
                      "The comparable class is person, which has few boxes; the interval shows how uncertain that comparison is. Fine-tuning on worksite images specialises the model: it no longer reports COCO classes such as car or bicycle.")
    name = "finetune-test" if a.include_test else "finetune-development"
    (EVIDENCE / f"{name}.json").write_text(json.dumps(rep, indent=2, default=float) + "\n")
    if a.include_test:
        TEST_RESULT.write_text(json.dumps({"checkpoint_sha256": sha, "generated_at": rep["generated_at"]}, indent=2) + "\n")
    print(json.dumps({k: rep["splits"][k] for k in rep["splits"]}, indent=2, default=float)[:3500]); return 0


def build_pretrained_baseline():
    m = fasterrcnn_mobilenet_v3_large_320_fpn(weights=FasterRCNN_MobileNet_V3_Large_320_FPN_Weights.COCO_V1, weights_backbone=None); return m.eval()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="video_investigator.training.finetune"); sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare").set_defaults(fn=cmd_prepare)
    t = sub.add_parser("train"); t.add_argument("--name", default="hardhat-v1"); t.add_argument("--epochs", type=int, default=DEFAULTS["epochs"]); t.add_argument("--seed", type=int, default=DEFAULTS["seed"])
    t.add_argument("--lr", type=float, default=DEFAULTS["lr"]); t.add_argument("--image-size", type=int, default=DEFAULTS["image_size"]); t.add_argument("--unfreeze-backbone", action="store_true"); t.set_defaults(fn=cmd_train)
    f = sub.add_parser("freeze"); f.add_argument("--name", default="hardhat-v1"); f.set_defaults(fn=cmd_freeze)
    e = sub.add_parser("evaluate"); e.add_argument("--name", default="hardhat-v1"); e.add_argument("--include-test", action="store_true"); e.set_defaults(fn=cmd_evaluate)
    a = ap.parse_args(argv); return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
