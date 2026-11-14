"""Embedding-based (semantic) retrieval over event evidence.

What is embedded: for every event, its saved evidence frames (full frames) and crops of the event's own tracked boxes taken from those frames.
A text query is embedded with the same model (CLIP-style joint space) and compared by cosine similarity.

Honest framing, enforced in the response contract:
  * similarity is a RANKING aid (cosine between a text embedding and an image embedding). It is not a probability, not a confidence that the
    event matches, and not comparable across queries or models. Raw CLIP scores sit in a narrow band (roughly 0.1 to 0.35).
  * every hit names the exact evidence item (kind, frame role, timestamp, box) that scored best, so it is traceable to source pixels.
  * structured constraints (type, class, zone, review status, time) are applied BEFORE ranking, never replaced by it.
The model is optional: if it cannot load, callers get EmbedderUnavailable and the rest of the application is unaffected.
"""
from __future__ import annotations
import hashlib, json, threading, time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence
import numpy as np
from PIL import Image

SCORE_MEANING = ("Cosine similarity between the query text and an evidence image in a joint embedding space. It orders results within this query only. "
                 "It is not a probability and not a confidence that the event matches.")
CROP_PAD = 0.10          # fractional padding around a tracked box when cropping
MIN_CROP_PX = 24         # crops smaller than this carry too little signal to embed
INDEX_VERSION = 1


class EmbedderUnavailable(Exception):
    def __init__(self, message: str):
        super().__init__(message); self.message = message


class Embedder(Protocol):
    name: str
    revision: str
    dim: int
    source: str            # "model" for the real encoder; "fixture" for test doubles, which must never be presented as real retrieval
    def embed_images(self, images: Sequence[Image.Image]) -> np.ndarray: ...
    def embed_texts(self, texts: Sequence[str]) -> np.ndarray: ...


class ClipEmbedder:
    """CLIP ViT-B/32 (LAION-2B, MIT licence) through transformers, on CPU."""
    name = "laion/CLIP-ViT-B-32-laion2B-s34B-b79K"
    revision = "1a25a446712ba5ee05982a381eed697ef9b435cf"
    dim = 512
    source = "model"

    def __init__(self):
        try:
            import torch
            from transformers import CLIPModel, CLIPProcessor
        except Exception as e:  # transformers missing
            raise EmbedderUnavailable(f"The semantic-search dependencies are not installed: {e}")
        try:
            self._torch = torch
            self.processor = CLIPProcessor.from_pretrained(self.name, revision=self.revision)
            self.model = CLIPModel.from_pretrained(self.name, revision=self.revision).eval()
        except Exception as e:  # offline, disk, corrupt download
            raise EmbedderUnavailable(f"The embedding model could not be loaded: {e}")

    def _norm(self, t) -> np.ndarray:
        # transformers 5 returns an output object whose pooler_output holds the projected embedding; older versions return the tensor.
        t = getattr(t, "pooler_output", t)
        a = t.detach().cpu().numpy().astype("float32")
        if a.ndim != 2 or a.shape[1] != self.dim:
            raise EmbedderUnavailable(f"Unexpected embedding shape {a.shape}; expected (n, {self.dim}). The model output format may have changed.")
        return a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-12)

    def embed_images(self, images):
        out = []
        with self._torch.inference_mode():
            for i in range(0, len(images), 16):
                inputs = self.processor(images=[im.convert("RGB") for im in images[i:i + 16]], return_tensors="pt")
                out.append(self._norm(self.model.get_image_features(**inputs)))
        return np.concatenate(out) if out else np.zeros((0, self.dim), "float32")

    def embed_texts(self, texts):
        with self._torch.inference_mode():
            inputs = self.processor(text=list(texts), return_tensors="pt", padding=True, truncation=True, max_length=77)
            return self._norm(self.model.get_text_features(**inputs))


_lock = threading.Lock()
_default: Embedder | None = None


def default_embedder() -> Embedder:
    """Lazily load the real model once per process."""
    global _default
    with _lock:
        if _default is None:
            _default = ClipEmbedder()
        return _default


# ---------------- index ----------------
@dataclass
class Item:
    event_key: str
    kind: str            # "frame" or "crop"
    role: str            # start | mid | end
    t_ms: int
    box: list[float] | None      # normalized xyxy of the crop in the upright frame, or None for a full frame
    track_id: int | None


def _crop(img: Image.Image, box, pad=CROP_PAD) -> Image.Image | None:
    w, h = img.size
    x1, y1, x2, y2 = box
    bw, bh = (x2 - x1) * w, (y2 - y1) * h
    if bw < MIN_CROP_PX or bh < MIN_CROP_PX:
        return None
    px, py = bw * pad, bh * pad
    return img.crop((max(0, int(x1 * w - px)), max(0, int(y1 * h - py)), min(w, int(x2 * w + px)), min(h, int(y2 * h + py))))


def index_dir(attempt_dir: Path) -> Path:
    return attempt_dir / "semantic"


def build_index(attempt_dir: Path, events: list[dict], observations: list[dict], embedder: Embedder, *, run_id: str, manifest_sha256: str) -> dict:
    """Embed evidence frames and crops for the given events and persist them next to (not inside) the published manifest. Derived and rebuildable."""
    by_t: dict[int, list[dict]] = {}
    for o in observations:
        by_t.setdefault(o["t_ms"], []).append(o)
    images: list[Image.Image] = []; items: list[Item] = []
    for e in events:
        key = e.get("event_key") or e["event_id"]          # events.json calls it event_id; the database calls it event_key
        for f in e["evidence"].get("frames", []):
            if f.get("missing") or not f.get("original"):
                continue
            path = attempt_dir / f["original"]
            if not path.is_file():
                continue
            img = Image.open(path).convert("RGB")
            images.append(img); items.append(Item(key, "frame", f["role"], f["t_ms"], None, None))
            for o in by_t.get(f["t_ms"], []):
                if o["track_id"] in e["track_ids"] and o["track_state"] == "confirmed":
                    c = _crop(img, o["box"])
                    if c is not None:
                        images.append(c); items.append(Item(key, "crop", f["role"], f["t_ms"], [round(x, 5) for x in o["box"]], o["track_id"]))
    emb = embedder.embed_images(images) if images else np.zeros((0, embedder.dim), "float32")
    d = index_dir(attempt_dir); d.mkdir(parents=True, exist_ok=True)
    np.save(d / "embeddings.npy", emb.astype("float32"))
    meta = {"index_version": INDEX_VERSION, "model": {"name": embedder.name, "revision": embedder.revision, "dim": embedder.dim, "source": embedder.source},
            "run_id": run_id, "source_manifest_sha256": manifest_sha256, "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "items": [i.__dict__ for i in items],
            "embeddings_sha256": hashlib.sha256((d / "embeddings.npy").read_bytes()).hexdigest(), "crop_pad": CROP_PAD, "min_crop_px": MIN_CROP_PX}
    (d / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def load_index(attempt_dir: Path, manifest_sha256: str) -> tuple[dict, np.ndarray] | None:
    """None when there is no index or it was built from a different manifest (stale)."""
    d = index_dir(attempt_dir)
    if not (d / "meta.json").is_file() or not (d / "embeddings.npy").is_file():
        return None
    meta = json.loads((d / "meta.json").read_text())
    if meta.get("source_manifest_sha256") != manifest_sha256 or meta.get("index_version") != INDEX_VERSION:
        return None
    if hashlib.sha256((d / "embeddings.npy").read_bytes()).hexdigest() != meta["embeddings_sha256"]:
        return None
    return meta, np.load(d / "embeddings.npy")


def rank_events(meta: dict, emb: np.ndarray, q: np.ndarray, allowed_event_keys: set[str] | None, limit: int, min_similarity: float | None = None) -> list[dict]:
    """Rank events by their best-scoring evidence item. Returns [{event_key, similarity, rank, best: item, runner_up_gap}] (all traceable)."""
    if len(emb) == 0:
        return []
    sims = emb @ q
    best: dict[str, tuple[float, int]] = {}
    for idx, it in enumerate(meta["items"]):
        if allowed_event_keys is not None and it["event_key"] not in allowed_event_keys:
            continue
        s = float(sims[idx])
        if it["event_key"] not in best or s > best[it["event_key"]][0]:
            best[it["event_key"]] = (s, idx)
    ranked = sorted(best.items(), key=lambda kv: (-kv[1][0], kv[0]))
    out = []
    for r, (key, (s, idx)) in enumerate(ranked, 1):
        if min_similarity is not None and s < min_similarity:
            continue
        out.append({"event_key": key, "similarity": round(s, 4), "rank": r, "best": meta["items"][idx]})
    return out[:limit]
