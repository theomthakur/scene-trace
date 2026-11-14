"""Structured event retrieval plus a bounded, transparent text parser.

The parser is NOT a language model and not semantic search. It recognises a small fixed vocabulary (event types, object classes,
zone names, review status, simple time constraints) and reports exactly what it understood and what it ignored. Intents the
platform cannot support from detections (blame, identity, "unattended", "abandoned", intent) return no events plus an explicit notice.
There is no relevance probability: results are ordered by start time.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

TYPE_WORDS = {
    "zone_entry": ["entry", "entries", "enter", "enters", "entered", "entering", "restricted", "intrusion", "intruded"],
    "stationary_object": ["stationary", "still", "static", "parked", "stopped", "motionless", "idle", "sitting"],
    "passage_occupancy": ["aisle", "aisles", "passage", "passages", "lane", "lanes", "blocked", "obstructed", "obstruction", "occupied", "occupancy", "overlap", "overlapping"],
}
CLASS_WORDS = {
    "person": ["person", "people", "pedestrian", "pedestrians", "man", "woman", "someone"], "bicycle": ["bicycle", "bicycles", "bike", "bikes"],
    "car": ["car", "cars", "vehicle", "vehicles"], "motorcycle": ["motorcycle", "motorbike", "scooter"], "bus": ["bus", "buses"], "truck": ["truck", "trucks", "lorry"],
    "backpack": ["backpack", "rucksack"], "handbag": ["handbag", "bag", "purse"], "suitcase": ["suitcase", "luggage"],
}
STATUS_WORDS = {"confirmed": "confirmed", "dismissed": "dismissed", "uncertain": "uncertain", "unreviewed": "unreviewed", "pending": "unreviewed"}
BLOCKED = {"unattended": "Unattended or abandoned items need evidence about who left them, which detections alone do not provide.",
           "abandoned": "Abandoned items need evidence about ownership, which detections alone do not provide.",
           "suspicious": "Suspicion is a judgement about intent; the platform does not infer intent.", "theft": "Theft is a judgement about intent; the platform does not infer intent.",
           "stole": "Theft is a judgement about intent; the platform does not infer intent.", "why": "Causal explanations are not generated; only observed events are retrieved.",
           "blame": "The platform does not assign blame.", "who": "The platform does not identify people.", "identify": "The platform does not identify people.",
           "face": "The platform does not use faces or identify people.", "intent": "The platform does not infer intent.", "violation": "Compliance judgements are not made from detections.",
           "unsafe": "Safety judgements are not made from detections.", "dangerous": "Safety judgements are not made from detections.", "compliant": "Compliance judgements are not made from detections."}
STOP = set("a an the of in on at to for and or with was were is are did do does when where what which show find me any all there that this it its by from during".split())


@dataclass
class Constraints:
    types: set[str] = field(default_factory=set)
    classes: set[str] = field(default_factory=set)
    zone_ids: set[str] = field(default_factory=set)
    review_status: set[str] = field(default_factory=set)
    after_ms: int | None = None
    before_ms: int | None = None
    recognised: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.types or self.classes or self.zone_ids or self.review_status or self.after_ms is not None or self.before_ms is not None)


def parse_query(text: str, zones: list[dict]) -> Constraints:
    c = Constraints()
    q = (text or "").lower()
    # time constraints: "after 3 s", "before 5 seconds", "between 2 and 6 s"
    m = re.search(r"between\s+(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds)?\s+and\s+(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds)?", q)
    if m:
        c.after_ms, c.before_ms = int(float(m.group(1)) * 1000), int(float(m.group(2)) * 1000)
        c.recognised.append(f"time between {m.group(1)} s and {m.group(2)} s"); q = q.replace(m.group(0), " ")
    for kw, attr in (("after", "after_ms"), ("before", "before_ms")):
        m = re.search(rf"{kw}\s+(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds)\b", q)
        if m and getattr(c, attr) is None:
            setattr(c, attr, int(float(m.group(1)) * 1000)); c.recognised.append(f"time {kw} {m.group(1)} s"); q = q.replace(m.group(0), " ")
    tokens = re.findall(r"[a-z0-9']+", q)
    used = set()
    for i, tok in enumerate(tokens):
        for t, words in TYPE_WORDS.items():
            if tok in words:
                c.types.add(t); used.add(i)
        for cl, words in CLASS_WORDS.items():
            if tok in words:
                c.classes.add(cl); used.add(i)
        if tok in STATUS_WORDS:
            c.review_status.add(STATUS_WORDS[tok]); used.add(i)
        if tok in BLOCKED:
            c.notices.append(BLOCKED[tok]); used.add(i)
    for z in zones:                                    # zone names match on any of their words, or the id
        words = [w for w in re.findall(r"[a-z0-9]+", z.get("name", "").lower()) if len(w) > 2 and w not in STOP and w not in ("zone", "strip")]
        if z["id"].lower() in q or (words and all(w in tokens for w in words)):
            c.zone_ids.add(z["id"])
    if c.types: c.recognised.append("event type: " + ", ".join(sorted(c.types)))
    if c.classes: c.recognised.append("object class: " + ", ".join(sorted(c.classes)))
    if c.zone_ids: c.recognised.append("zone: " + ", ".join(sorted(c.zone_ids)))
    if c.review_status: c.recognised.append("review status: " + ", ".join(sorted(c.review_status)))
    mentioned = {w for ws in TYPE_WORDS.values() for w in ws} | {w for ws in CLASS_WORDS.values() for w in ws} | set(STATUS_WORDS) | set(BLOCKED)
    c.ignored = sorted({t for t in tokens if t not in STOP and t not in mentioned and not t.isdigit() and t not in ("s", "sec", "secs", "seconds", "and", "between", "after", "before")
                        and not any(t in re.findall(r"[a-z0-9]+", z.get("name", "").lower()) for z in zones if z["id"] in c.zone_ids)})
    return c


def apply(events: list[dict], c: Constraints, limit: int) -> list[dict]:
    out = []
    for e in events:
        if c.types and e["type"] not in c.types: continue
        if c.classes and e["class_name"] not in c.classes: continue
        if c.zone_ids and e["zone_id"] not in c.zone_ids: continue
        if c.review_status and e["review_status"] not in c.review_status: continue
        if c.after_ms is not None and e["end_ms"] < c.after_ms: continue
        if c.before_ms is not None and e["start_ms"] > c.before_ms: continue
        out.append(e)
    out.sort(key=lambda e: (e["start_ms"], e["id"]))
    return out[:limit]
