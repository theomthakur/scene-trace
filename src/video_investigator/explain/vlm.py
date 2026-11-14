"""Optional video-language explanations grounded in an event's own evidence.

What the model sees: by default one close-up crop of the object the rule tracked (the middle evidence frame); the caller may select other
frames. All images come from the UNANNOTATED saved frames. What it is told: only to describe what is visible, to say when it cannot tell, and
not to guess identity, intent or cause. The event record is shown NEXT to the answer, not fed to the model (a pilot showed a 500M model parrots
prompt text such as times and labels, and that several images at once made it hallucinate much more).

What the platform does with the answer (it never trusts it):
  * stores it with the exact frames, times, model revision and a hash of the prompt, so it is reproducible and auditable;
  * runs automatic checks and attaches flags: unsupported inference words, times outside the evidence, and supported object classes the
    text mentions that the detector did not report in those frames;
  * labels it as model-generated, unverified text. It never changes an event, a review or a report's counts.
If the model cannot load, callers get ExplainerUnavailable and the rest of the application is unaffected.
"""
from __future__ import annotations
import hashlib, re, threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence
from PIL import Image
from ..events.rules import TYPE_LABEL
from ..search.engine import BLOCKED

DISCLAIMER = ("Model-generated description of the saved evidence frames. It is unverified, can be wrong or invent details, and is not a finding: "
              "the event, its rule and your review decision are what count.")
# 'who' and 'why' are ordinary relative words in a description, so they are not flagged here even though search refuses them as intents.
INFERENCE_WORDS = (set(BLOCKED) - {"who", "why"}) | {"trying", "tried", "attempting", "intends", "intending", "wants", "wanted", "probably", "apparently", "must", "criminal", "guilty", "dangerous",
                                  "angry", "nervous", "stealing", "stolen", "loiter", "loitering", "lurking", "casing", "waiting for"}
OBJECT_WORDS = {"person": ("person", "people", "man", "woman", "pedestrian", "pedestrians", "child", "boy", "girl", "cyclist"), "bicycle": ("bicycle", "bike", "bikes"),
                "car": ("car", "cars", "vehicle", "van", "taxi"), "motorcycle": ("motorcycle", "motorbike", "scooter"), "bus": ("bus",), "truck": ("truck", "lorry"),
                "backpack": ("backpack", "rucksack"), "handbag": ("handbag", "purse", "bag", "bags"), "suitcase": ("suitcase", "luggage")}
CROP_PAD = 0.15
MAX_NEW_TOKENS = 110


class ExplainerUnavailable(Exception):
    def __init__(self, message: str):
        super().__init__(message); self.message = message


class Explainer(Protocol):
    name: str
    revision: str
    source: str          # "model" for the real VLM; "fixture" for test doubles
    def generate(self, images: Sequence[Image.Image], prompt: str) -> str: ...


class SmolVlmExplainer:
    """SmolVLM-500M-Instruct (Apache-2.0) through transformers on CPU. Chosen because it is small enough to run locally; it is weak and says so in its flags."""
    name = "HuggingFaceTB/SmolVLM-500M-Instruct"
    revision = "753c1752602b5e739af7a7fa6947a635051897a3"
    source = "model"
    IMAGE_EDGE = 512

    def __init__(self):
        try:
            import torch
            from transformers import AutoModelForImageTextToText, AutoProcessor
        except Exception as e:
            raise ExplainerUnavailable(f"The explanation dependencies are not installed: {e}")
        try:
            self._torch = torch
            self.processor = AutoProcessor.from_pretrained(self.name, revision=self.revision, do_image_splitting=False, size={"longest_edge": self.IMAGE_EDGE})
            self.model = AutoModelForImageTextToText.from_pretrained(self.name, revision=self.revision, dtype=torch.float32).eval()
        except Exception as e:
            raise ExplainerUnavailable(f"The explanation model could not be loaded: {e}")
        self._lock = threading.Lock()

    def generate(self, images, prompt):
        msgs = [{"role": "user", "content": [{"type": "image"} for _ in images] + [{"type": "text", "text": prompt}]}]
        with self._lock, self._torch.inference_mode():       # one generation at a time: CPU-heavy
            inputs = self.processor(text=self.processor.apply_chat_template(msgs, add_generation_prompt=True), images=list(images), return_tensors="pt")
            out = self.model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False, repetition_penalty=1.15)
        return self.processor.batch_decode(out[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True)[0].strip()


_lock = threading.Lock()
_default: Explainer | None = None


def default_explainer() -> Explainer:
    global _default
    with _lock:
        if _default is None:
            _default = SmolVlmExplainer()
        return _default


# ---------------- grounding ----------------
@dataclass
class Grounding:
    images: list[Image.Image]
    labels: list[str]            # human-readable label per image, in order
    frames: list[dict]           # [{role, t_ms, kind}] for storage and display
    prompt: str
    prompt_sha256: str
    detected_classes: set[str]


def _crop(img: Image.Image, box) -> Image.Image | None:
    w, h = img.size; x1, y1, x2, y2 = box
    bw, bh = (x2 - x1) * w, (y2 - y1) * h
    if bw < 24 or bh < 24:
        return None
    return img.crop((max(0, int(x1 * w - bw * CROP_PAD)), max(0, int(y1 * h - bh * CROP_PAD)), min(w, int(x2 * w + bw * CROP_PAD)), min(h, int(y2 * h + bh * CROP_PAD))))


def ground(attempt_dir: Path, event: dict, observations: Sequence[dict], roles: Sequence[str] = ("mid",)) -> Grounding:
    """Pick the evidence images. roles selects which saved frames (start, mid, end) are used; each contributes a crop of the tracked box, or the
    full frame when no usable crop exists. Raises ExplainerUnavailable when the event has no usable frames."""
    by_t: dict[int, list[dict]] = {}
    for o in observations:
        by_t.setdefault(o["t_ms"], []).append(o)
    images: list[Image.Image] = []; labels: list[str] = []; frames: list[dict] = []; detected: set[str] = set()
    for f in event["evidence"].get("frames", []):
        if f.get("missing") or not f.get("original") or f["role"] not in roles:
            continue
        img = Image.open(attempt_dir / f["original"]).convert("RGB")
        at = by_t.get(f["t_ms"], [])
        detected |= {o["class_name"] for o in at if o["track_state"] == "confirmed"}
        crop = None
        for o in at:
            if o["track_id"] in event["track_ids"] and o["track_state"] == "confirmed":
                crop = _crop(img, o["box"]); break
        if crop is not None:
            images.append(crop); labels.append(f"crop of the tracked {event['class_name']} at {f['t_ms'] / 1000:.1f} s"); frames.append({"role": f["role"], "t_ms": f["t_ms"], "kind": "crop"})
        else:
            images.append(img); labels.append(f"full frame at {f['t_ms'] / 1000:.1f} s"); frames.append({"role": f["role"], "t_ms": f["t_ms"], "kind": "frame"})
    if not images:
        raise ExplainerUnavailable("This event has no usable evidence frames to explain.")
    cls = event["class_name"]
    if len(images) == 1:
        prompt = f"Describe this {cls}: clothing or colours, what they are doing, and anything they carry. Two sentences. If you cannot tell, say so."
    else:
        prompt = (f"These are images of the same {cls} at different moments, in time order. Describe the {cls}: clothing or colours, and how they move between the images. "
                  "Two sentences. If you cannot tell, say so.")
    return Grounding(images, labels, frames, prompt, hashlib.sha256(prompt.encode()).hexdigest(), detected)


# ---------------- checks (the answer is never trusted) ----------
IDENTIFIER = re.compile(r"\b(?=[A-Za-z0-9-]*\d)(?=[A-Za-z0-9-]*[A-Za-z])[A-Za-z0-9-]{5,}\b|\b[A-Z]{1,3}[- ][A-Z]{1,2}[- ]?\d{2,4}\b")


def redact_identifiers(text: str) -> tuple[str, list[str]]:
    """Licence-plate-like or other mixed letter-digit identifiers are replaced before anything is stored or shown: this platform does not read plates or IDs."""
    found = [m.group(0) for m in IDENTIFIER.finditer(text)]
    return (IDENTIFIER.sub("[redacted]", text), found)
def check_text(text: str, event: dict, detected_classes: set[str], padding_ms: int = 3000) -> list[str]:
    flags: list[str] = []
    words = set(re.findall(r"[a-z']+", text.lower()))
    hits = sorted(w for w in INFERENCE_WORDS if (" " in w and w in text.lower()) or w in words)
    if hits:
        flags.append("unsupported_inference_words: " + ", ".join(hits))
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:s\b|sec|seconds)", text.lower()):
        t = float(m.group(1)) * 1000
        if t < event["start_ms"] - padding_ms or t > event["end_ms"] + padding_ms:
            flags.append(f"time_outside_evidence: {m.group(0).strip()}")
    for cls, ws in OBJECT_WORDS.items():
        if any(w in words for w in ws) and cls not in detected_classes and cls != event["class_name"]:
            flags.append(f"mentions_object_not_in_detections: {cls}")
    if len(text.strip()) < 12 or re.search(r"(#\d{3,}|(\b\w+\b)(\s+\2){3,})", text):
        flags.append("degenerate_output")
    filler = {"a", "an", "the", "is", "are", "was", "of", "in", "on", "at", "to", "and", "with", "this", "that", "it", "its", "s", "seconds", "tracked", "from"} | {w for ws in OBJECT_WORDS.values() for w in ws}
    content = [w for w in re.findall(r"[a-z]+", text.lower()) if w not in filler]
    if len(content) < 3:
        flags.append("uninformative: the text adds almost nothing beyond the object class")
    return flags


def explain(attempt_dir: Path, event: dict, observations: Sequence[dict], explainer: Explainer, roles: Sequence[str] = ("mid",)) -> dict:
    g = ground(attempt_dir, event, observations, roles)
    text = explainer.generate(g.images, g.prompt)
    text, ids = redact_identifiers(text)
    flags = check_text(text, event, g.detected_classes)
    if ids:
        flags.append(f"identifier_redacted: {len(ids)} identifier-like string(s) removed; this platform does not read plates or IDs")
    if len(g.images) > 1:
        flags.append("multi_image_input: this small model is markedly less reliable with several images")
    return {"status": "flagged" if flags else "ok", "text": text, "flags": flags, "frames": g.frames, "labels": g.labels, "prompt": g.prompt, "prompt_sha256": g.prompt_sha256,
            "model": {"name": explainer.name, "revision": explainer.revision, "source": explainer.source}, "disclaimer": DISCLAIMER}
