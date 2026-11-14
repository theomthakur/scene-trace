"""Real-footage evidence for appearance-based association, with the limits stated.  python scripts/eval_crosscam.py -> docs/evidence/crosscam-eval.json

There are NO multi-camera identity labels in this project, so true cross-camera accuracy is not measured. What IS measured on real tracks:
  * negative control: tracks that are visible at the same moment cannot be the same object. Their descriptor similarity shows how often the appearance signal
    would wrongly link two different objects (false-match rate at a threshold).
  * positive proxy: the two halves of ONE track are the same object by construction (assuming no tracker identity switch). Same camera and lighting, so this is
    an easier positive than a real cross-camera match: it is an upper bound, not an estimate.
Both use the descriptor the associator uses (mean CLIP crop embedding). Class gating is not applied to the control so the signal is not hidden by it."""
import json, sys, time, itertools
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "src"))
from video_investigator.crosscam import descriptors as D
from video_investigator.search import semantic

CLIPS = {"pedestrian_area": ("person", "var/candidates/pedestrian_area.webm"), "rush_hour": ("car", "var/candidates/rush_hour.webm")}
TAUS = [0.70, 0.75, 0.80, 0.85, 0.90, 0.95]


def analyse(name, cls, video, emb):
    att = sorted((ROOT / "var" / "semantic-eval" / "runs" / name).glob("attempt-*"))[-1]
    obs = [json.loads(l) for l in (att / "observations.jsonl").read_text().splitlines()]
    tracks = D.track_observations(obs, min_obs=3, classes=[cls]); crops = D.embed_track_crops(ROOT / video, obs, emb, tracks, k=6)
    desc = {tid: D.mean_descriptor([e for _, e in c]) for tid, c in crops.items() if c}
    span = {tid: (min(o["t_ms"] for o in v), max(o["t_ms"] for o in v)) for tid, v in tracks.items() if tid in desc}
    times = {tid: {o["t_ms"] for o in v} for tid, v in tracks.items()}
    neg = []
    for a, b in itertools.combinations(sorted(desc), 2):
        if len(times[a] & times[b]) >= 2:                       # visible together in at least two sampled frames: different objects
            neg.append(float(desc[a] @ desc[b]))
    pos = []
    for tid, c in crops.items():
        if len(c) >= 4:
            half = len(c) // 2; pos.append(float(D.mean_descriptor([e for _, e in c[:half]]) @ D.mean_descriptor([e for _, e in c[half:]])))
    neg, pos = np.array(neg), np.array(pos)
    stat = lambda x: {"n": int(len(x)), "mean": round(float(x.mean()), 4), "p50": round(float(np.percentile(x, 50)), 4), "p95": round(float(np.percentile(x, 95)), 4), "max": round(float(x.max()), 4)} if len(x) else {"n": 0}
    curve = [{"threshold": t, "false_match_rate_covisible": (round(float((neg >= t).mean()), 4) if len(neg) else None), "false_matches": int((neg >= t).sum()),
              "same_track_recall_proxy": (round(float((pos >= t).mean()), 4) if len(pos) else None)} for t in TAUS]
    return {"class": cls, "tracks_used": len(desc), "covisible_negative_pairs": stat(neg), "same_track_halves_positive_proxy": stat(pos), "by_threshold": curve}


def main():
    emb = semantic.default_embedder(); res = {n: analyse(n, c, v, emb) for n, (c, v) in CLIPS.items()}
    rep = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "descriptor": {"model": emb.name, "revision": emb.revision, "crops_per_track": 6, "pooling": "mean, L2-normalised"},
           "clips": res, "limits": ["No multi-camera identity ground truth exists here: true cross-camera precision and recall are NOT measured.",
                                    "Co-visible pairs are certain negatives; they are the hardest realistic negatives only inside one scene.",
                                    "Same-track halves are an easy positive (same camera, same lighting): the recall column is an upper bound.",
                                    "General CLIP embeddings are not person re-identification features. Treat any proposed link as a reviewer hint."]}
    (ROOT / "docs" / "evidence" / "crosscam-eval.json").write_text(json.dumps(rep, indent=2) + "\n")
    for n, r in res.items():
        print(n, "tracks", r["tracks_used"], "neg", r["covisible_negative_pairs"], "pos", r["same_track_halves_positive_proxy"])
        for c in r["by_threshold"]: print("  ", c)


if __name__ == "__main__":
    main()
