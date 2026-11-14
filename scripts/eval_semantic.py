"""Evaluate semantic retrieval with the REAL embedding model on labelled queries (fixtures/benchmark/semantic_queries.json).

  python scripts/eval_semantic.py            writes docs/evidence/semantic-eval.json

Compared, per query, over the same 21-event corpus:
  semantic (all events)     CLIP similarity ranking with no structured filter
  hybrid (as the API does)  structured class words from the query filter first, then CLIP ranks the rest
  class filter by time      what structured search alone can do: the class filter, in time order
  random                    expected value of a uniformly random order (computed exactly, no sampling)
Metrics: Recall@1/3/5 (a query is a hit if any relevant event is in the top k) and MRR of the first relevant event. Ambiguous events are removed
from the ranking for that query. Similarity scores are never reported as confidence."""
import json, sys, time
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "src"))
from video_investigator.config import load_settings
from video_investigator.runner import process_video, zones_from_dicts
from video_investigator.search import engine as search_engine, semantic

CLIPS = {"pedestrian_area": ("var/candidates/pedestrian_area.webm", "fixtures/zones/pedestrian_area.json"), "rush_hour": ("var/candidates/rush_hour.webm", "fixtures/zones/rush_hour.json")}
OUT = ROOT / "var" / "semantic-eval" / "runs"


def corpus():
    s = load_settings(); events, index = [], {}
    for name, (video, zones) in CLIPS.items():
        if not list((OUT / name).glob("attempt-*/manifest.json")):
            process_video(ROOT / video, zones_from_dicts(json.loads((ROOT / zones).read_text())), s, OUT, run_id=name)
        att = sorted((OUT / name).glob("attempt-*"))[-1]
        evs = json.loads((att / "events.json").read_text()); obs = [json.loads(l) for l in (att / "observations.jsonl").read_text().splitlines()]
        man = json.loads((att / "manifest.json").read_text())["files"]
        emb = semantic.default_embedder()
        meta = semantic.build_index(att, evs, obs, emb, run_id=name, manifest_sha256=name + ":" + man["events.json"][:16])
        index[name] = (meta, np.load(att / "semantic" / "embeddings.npy"))
        for e in evs:
            events.append({"event_key": e["event_id"], "clip": name, "type": e["type"], "class_name": e["class_name"], "zone_id": e["zone_id"], "start_ms": e["start_ms"], "end_ms": e["end_ms"]})
    return events, index


def first_rank(order, relevant):
    for i, k in enumerate(order, 1):
        if k in relevant:
            return i
    return None


def metrics(ranks, n_pool_each):
    n = len(ranks)
    def rec(k): return sum(1 for r in ranks if r is not None and r <= k) / n
    return {"recall@1": rec(1), "recall@3": rec(3), "recall@5": rec(5), "mrr": sum(1 / r for r in ranks if r) / n, "queries": n}


def main():
    spec = json.loads((ROOT / "fixtures" / "benchmark" / "semantic_queries.json").read_text())
    events, index = corpus(); emb = semantic.default_embedder()
    by_key = {e["event_key"]: e for e in events}
    zones = []
    res = {"semantic_all": [], "hybrid": [], "class_filter_time": [], "random_expected": []}; per = []
    for q in spec["queries"]:
        relevant, ambiguous = set(q["relevant"]), set(q["ambiguous"])
        qv = emb.embed_texts([q["q"]])[0]
        # semantic over every event of both clips: rank per clip index, then merge by similarity (one shared embedding space)
        allr = []
        for name, (meta, E) in index.items():
            allr += semantic.rank_events(meta, E, qv, None, 1000)
        allr.sort(key=lambda h: -h["similarity"]); order_all = [h["event_key"] for h in allr if h["event_key"] not in ambiguous]
        # hybrid: class words in the query filter first (exactly what the API does), then similarity ranks the remaining pool
        c = search_engine.parse_query(q["q"], zones)
        pool = [e for e in events if (not c.classes or e["class_name"] in c.classes)]
        keys = {e["event_key"] for e in pool}
        hyb = []
        for name, (meta, E) in index.items():
            hyb += semantic.rank_events(meta, E, qv, keys, 1000)
        hyb.sort(key=lambda h: -h["similarity"]); order_h = [h["event_key"] for h in hyb if h["event_key"] not in ambiguous]
        order_c = [e["event_key"] for e in sorted(pool, key=lambda e: (e["clip"], e["start_ms"])) if e["event_key"] not in ambiguous]
        n_pool = len(order_h)
        r_rand = None
        res["semantic_all"].append(first_rank(order_all, relevant)); res["hybrid"].append(first_rank(order_h, relevant)); res["class_filter_time"].append(first_rank(order_c, relevant))
        # exact expectation for a uniform random order: first of m relevant among n is at expected position (n+1)/(m+1)
        m = len([k for k in relevant if k in order_h]); res["random_expected"].append(((n_pool + 1) / (m + 1)) if m else None)
        top = hyb[:3]
        per.append({"query": q["q"], "pool_after_class_filter": n_pool, "relevant": sorted(relevant), "ambiguous_ignored": sorted(ambiguous), "classes_from_text": sorted(c.classes),
                    "first_relevant_rank": {"semantic_all": res["semantic_all"][-1], "hybrid": res["hybrid"][-1], "class_filter_time": res["class_filter_time"][-1]},
                    "hybrid_top3": [{"event": h["event_key"], "clip": by_key[h["event_key"]]["clip"], "similarity": h["similarity"], "best_item": h["best"]} for h in top]})
    out = {k: (metrics(v, None) if k != "random_expected" else {"mean_first_relevant_rank": float(np.mean([x for x in v if x])), "mrr_approx_note": "expected rank, not a ranked-list metric"}) for k, v in res.items()}
    rep = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "model": {"name": emb.name, "revision": emb.revision, "dim": emb.dim}, "corpus_events": len(events),
           "queries": len(spec["queries"]), "annotation": spec["annotation"], "metrics": out, "per_query": per,
           "reading": "Similarity is a ranking aid, not a confidence. Eleven queries over 21 events from two clips, one annotator: descriptive only, no claim about other footage."}
    (ROOT / "docs" / "evidence" / "semantic-eval.json").write_text(json.dumps(rep, indent=2, default=float) + "\n")
    print(json.dumps({"metrics": out}, indent=2, default=float))


if __name__ == "__main__":
    main()
