"""Timestamp-linked reports (JSON, Markdown, HTML). Every report carries source and run hashes and the limitations text."""
from __future__ import annotations
import html, json
from datetime import datetime, timezone

LIMITATIONS = [
    "Detections come from a general-purpose COCO model. They are not verified identifications and can miss or misclassify objects.",
    "Track IDs are temporary identifiers within one run. They do not identify people and are not re-identified after a long disappearance.",
    "Events are rule-based candidates over noisy detections. 2D image overlap is not physical clearance, and a stationary object is not called unattended or abandoned.",
    "A run with no events is not a certified incident-free video: check the quality flags and the coverage of the zones.",
    "Detector confidence is a model score, not a calibrated probability of the event being real.",
]


def _ts(ms: int) -> str:
    s = ms / 1000.0
    return f"{int(s // 60):02d}:{s % 60:05.2f}"


def build_report(run: dict, video: dict, events: list[dict]) -> dict:
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "run": run, "video": video, "events": events, "limitations": LIMITATIONS,
            "counts": {"events": len(events), "by_review": {k: sum(1 for e in events if e["review_status"] == k) for k in ("unreviewed", "confirmed", "dismissed", "uncertain")}},
            "data_source": "real detector output on decoded video pixels" if all(e["source"] == "detector" for e in events) else "contains fixture-tagged events"}


def to_markdown(r: dict) -> str:
    run, video = r["run"], r["video"]
    L = [f"# Investigation report: {video['display_name']}", "", f"Generated {r['generated_at']}", "",
         "## Source and run", f"- Video SHA-256: `{video['source_sha256']}`", f"- Duration: {_ts(video['duration_ms'])} ({video['width']}x{video['height']})",
         f"- Run: `{run['id']}`, attempt {run['attempt']}, state {run['state']}", f"- Pipeline: {run.get('pipeline_version')}, config hash `{run['config_hash']}`",
         f"- Manifest SHA-256: `{run.get('manifest_sha256')}`", f"- Detector: {(run.get('detector') or {}).get('name')} {(run.get('detector') or {}).get('weights')}, weights `{(run.get('detector') or {}).get('weights_sha256')}`",
         f"- Quality flags: {', '.join(run.get('quality_flags') or []) or 'none'}", f"- Data source: {r['data_source']}", "", "## Events"]
    if not r["events"]:
        L.append("No events were produced. This does not certify that the video is incident-free.")
    for e in r["events"]:
        L += ["", f"### {e['description']}", f"- Time: {_ts(e['start_ms'])} to {_ts(e['end_ms'])} ({e['start_ms']} to {e['end_ms']} ms)",
              f"- Review: {e['review_status']}" + (f" - {e['review_note']}" if e["review_note"] else ""),
              f"- Rule: {e['details'].get('rule')}", f"- Uncertainty flags: {', '.join(e['uncertainty_flags']) or 'none'}", f"- Source: {e['source']}"]
        for f in e["evidence"].get("frames", []):
            if not f.get("missing"):
                L.append(f"- Evidence frame ({f['role']} at {f['t_ms']} ms): {f['overlay']}")
        if e["evidence"].get("clip"):
            L.append(f"- Clip: {e['evidence']['clip']} (range {e['evidence']['clip_range_ms'][0]} to {e['evidence']['clip_range_ms'][1]} ms)")
    L += ["", "## Limitations"] + [f"- {x}" for x in r["limitations"]]
    return "\n".join(L) + "\n"


def to_html(r: dict) -> str:
    md = to_markdown(r)
    body = "".join(f"<p>{html.escape(line)}</p>" if line and not line.startswith(("#", "-")) else (f"<h3>{html.escape(line.lstrip('# '))}</h3>" if line.startswith("#") else (f"<li>{html.escape(line[2:])}</li>" if line.startswith("-") else "")) for line in md.splitlines())
    return f"<!doctype html><meta charset='utf-8'><title>Investigation report</title><style>body{{font:15px/1.5 system-ui;max-width:780px;margin:2rem auto;color:#10213f}}code{{font-size:12px}}</style>{body}"
