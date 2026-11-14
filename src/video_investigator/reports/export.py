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
    """Render a readable HTML report from structured data, with all user content escaped."""
    esc = lambda value: html.escape(str(value if value is not None else "Not available"))
    run, video = r["run"], r["video"]
    cards = []
    for index, event in enumerate(r["events"], 1):
        flags = ", ".join(event.get("uncertainty_flags") or []) or "None"
        note = event.get("review_note") or "No review note"
        frames = "".join(f"<li>{esc(f.get('role'))} · {esc(_ts(f.get('t_ms', 0)))} · {esc(f.get('overlay'))}</li>" for f in event.get("evidence", {}).get("frames", []) if not f.get("missing")) or "<li>No evidence frames available</li>"
        cards.append(f"<article class='event'><div class='event-head'><span>EVENT {index:02d}</span><span class='status'>{esc(event['review_status'])}</span></div><h3>{esc(event['description'])}</h3><p class='time'>{esc(_ts(event['start_ms']))} - {esc(_ts(event['end_ms']))}</p><div class='event-grid'><div><small>REVIEW NOTE</small><p>{esc(note)}</p></div><div><small>UNCERTAINTY</small><p>{esc(flags)}</p></div></div><details><summary>Evidence and rule details</summary><p>Rule: {esc(event.get('details', {}).get('rule'))} · Source: {esc(event.get('source'))}</p><ul>{frames}</ul><p>Context clip: {esc(event.get('evidence', {}).get('clip') or 'Not available')}</p></details></article>")
    event_html = "".join(cards) or "<p>No events were produced. This does not certify that the video is incident-free.</p>"
    limits = "".join(f"<li>{esc(item)}</li>" for item in r["limitations"])
    counts = r["counts"]["by_review"]
    css = """*{box-sizing:border-box}body{margin:0;background:#f3f3f0;color:#1b2733;font:15px/1.6 system-ui,-apple-system,sans-serif}main{max-width:1040px;margin:auto;padding:48px 24px 80px}.eyebrow{font-size:11px;font-weight:700;letter-spacing:.15em;color:#708188}h1{font-size:clamp(32px,5vw,48px);letter-spacing:-.045em;line-height:1.1;margin:12px 0}h2{font-size:21px;letter-spacing:-.03em;margin:0 0 18px}h3{font-size:18px;margin:10px 0}.lead{color:#64767e}.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:#dfe5e2;border:1px solid #dfe5e2;border-radius:14px;overflow:hidden;margin:30px 0}.summary div{background:white;padding:20px}.summary strong{display:block;font-size:28px}.summary span,small{font-size:11px;color:#73858a;letter-spacing:.09em;text-transform:uppercase}.event{background:white;border:1px solid #e0e5e2;border-radius:14px;padding:24px;margin-bottom:14px}.event-head{display:flex;justify-content:space-between;color:#75868c;font-size:11px;font-weight:700;letter-spacing:.12em}.status{color:#34586c}.time{color:#61747d;font-variant-numeric:tabular-nums}.event-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;border-top:1px solid #edf0ee;padding-top:16px}.event-grid p{margin:4px 0}details{margin:20px 0;border-top:1px solid #e0e5e2;padding-top:14px}summary{cursor:pointer;font-weight:650}.metadata{overflow-wrap:anywhere;color:#53666c}.limitations{color:#53666c} @media(max-width:600px){.summary{grid-template-columns:repeat(2,1fr)}.event-grid{grid-template-columns:1fr}} @media print{body{background:white}main{padding:0}.event{break-inside:avoid}}"""
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>SceneTrace | Investigation report</title><style>{css}</style></head><body><main><p class='eyebrow'>SCENETRACE / INVESTIGATION REPORT</p><h1>{esc(video['display_name'])}</h1><p class='lead'>A review of detected events and supporting evidence · Generated {esc(r['generated_at'])}</p><div class='summary'><div><span>Total events</span><strong>{r['counts']['events']}</strong></div><div><span>Confirmed</span><strong>{counts['confirmed']}</strong></div><div><span>Unreviewed</span><strong>{counts['unreviewed']}</strong></div><div><span>Uncertain</span><strong>{counts['uncertain']}</strong></div></div><h2>Findings</h2>{event_html}<details><summary>Source, run and limitations</summary><div class='metadata'><p>Video SHA-256: {esc(video['source_sha256'])}<br>Duration: {esc(_ts(video['duration_ms']))} · {esc(video['width'])} × {esc(video['height'])}<br>Run: {esc(run['id'])} · Attempt {esc(run['attempt'])} · {esc(run['state'])}<br>Pipeline: {esc(run.get('pipeline_version'))}<br>Config hash: {esc(run.get('config_hash'))}<br>Manifest SHA-256: {esc(run.get('manifest_sha256'))}<br>Detector: {esc((run.get('detector') or {}).get('name'))} · {esc((run.get('detector') or {}).get('weights'))}<br>Weights SHA-256: {esc((run.get('detector') or {}).get('weights_sha256'))}<br>Data source: {esc(r['data_source'])}<br>Quality flags: {esc(', '.join(run.get('quality_flags') or []) or 'None')}</p><ul class='limitations'>{limits}</ul></div></details></main></body></html>"""
