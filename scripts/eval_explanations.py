"""Generate explanations with the REAL vision-language model for the 21 benchmark events and score them against the written rubric
(fixtures/benchmark/explanation_rubric.json).   python scripts/eval_explanations.py   ->  docs/evidence/explanation-eval.json

Reported: rubric verdict counts, how often the model invents details, how often it says it cannot tell, how the platform's AUTOMATIC flags line up with
the rubric (do flags catch the bad ones? how many flags are noise?), and latency. Ratings are bound to the exact text they judged by hash; if the model's
output changes, the stale ratings are listed instead of being silently reused."""
import collections, hashlib, json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "src"))
from video_investigator.explain import vlm

RUNS = ROOT / "var" / "semantic-eval" / "runs"


def main():
    rub = json.loads((ROOT / "fixtures" / "benchmark" / "explanation_rubric.json").read_text()); ex = vlm.SmolVlmExplainer(); rows = []
    for clip in ("pedestrian_area", "rush_hour"):
        att = sorted((RUNS / clip).glob("attempt-*"))[-1]
        evs = json.loads((att / "events.json").read_text()); obs = [json.loads(l) for l in (att / "observations.jsonl").read_text().splitlines()]
        for e in evs:
            t0 = time.time(); r = vlm.explain(att, e, obs, ex); r["secs"] = round(time.time() - t0, 2)
            raw = ex.generate(*(lambda g: (g.images, g.prompt))(vlm.ground(att, e, obs)))          # deterministic: the same raw text the rating judged
            r.update(event_id=e["event_id"], clip=clip, raw_text_sha256=hashlib.sha256(raw.encode()).hexdigest()); rows.append(r)
    stale = [r["event_id"] for r in rows if rub["ratings"][r["event_id"]]["rated_text_sha256"] != r["raw_text_sha256"]]
    rated = [r for r in rows if r["event_id"] not in stale]
    bad = lambda r: rub["ratings"][r["event_id"]]["verdict"] == "mostly_unsupported" or rub["ratings"][r["event_id"]]["invented"]
    verdicts = collections.Counter(rub["ratings"][r["event_id"]]["verdict"] for r in rated)
    flagged = [r for r in rated if r["status"] == "flagged"]; tp = sum(1 for r in flagged if bad(r)); fn = sum(1 for r in rated if r["status"] == "ok" and bad(r))
    rep = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "model": {"name": ex.name, "revision": ex.revision}, "events": len(rows), "rated": len(rated), "stale_ratings": stale,
           "annotation": rub["annotation"], "rubric": rub["rubric"], "verdicts": dict(verdicts),
           "invented_detail": {"count": sum(rub["ratings"][r["event_id"]]["invented"] for r in rated), "of": len(rated)},
           "states_uncertainty": {"count": sum(rub["ratings"][r["event_id"]]["states_uncertainty"] for r in rated), "of": len(rated)},
           "automatic_flags": {"flagged": len(flagged), "of": len(rated), "flagged_and_bad": tp, "flagged_but_not_bad": len(flagged) - tp, "bad_but_not_flagged": fn,
                               "bad_total": sum(1 for r in rated if bad(r)), "note": "'bad' = rubric verdict mostly_unsupported OR an invented detail. Flags are cheap string checks, not a verifier."},
           "latency_s": {"mean": round(sum(r["secs"] for r in rows) / len(rows), 2), "max": max(r["secs"] for r in rows)},
           "identifier_redactions": sum(1 for r in rows if any(f.startswith("identifier_redacted") for f in r["flags"])),
           "items": [{"event_id": r["event_id"], "clip": r["clip"], "text": r["text"], "flags": r["flags"], "status": r["status"], "rating": rub["ratings"][r["event_id"]]["verdict"], "note": rub["ratings"][r["event_id"]]["note"]} for r in rows],
           "reading": "A 500M-parameter model on 21 crops, one rater. Most descriptions mix real and invented details, so the UI labels them unverified and never lets them alter an event."}
    (ROOT / "docs" / "evidence" / "explanation-eval.json").write_text(json.dumps(rep, indent=2) + "\n")
    print(json.dumps({k: rep[k] for k in ("events", "rated", "stale_ratings", "verdicts", "invented_detail", "states_uncertainty", "automatic_flags", "latency_s", "identifier_redactions")}, indent=2))


if __name__ == "__main__":
    main()
