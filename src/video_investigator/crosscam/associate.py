"""Cross-camera association of tracks: a CANDIDATE-linking aid for a human reviewer. It does not identify people.

Method (deliberately conservative):
  1. Gating: only tracks of the same object class, from different cameras, whose time gap is plausible (camera B's track starts between min_gap and
     max_gap seconds after camera A's track ends, in a shared clock) can be paired.
  2. Appearance: cosine similarity between per-track descriptors (the mean of a few crop embeddings). General-purpose image embeddings are NOT
     person re-identification features, so similarity is weak evidence and is reported as such.
  3. Assignment: one-to-one (Hungarian) on the gated similarities, then a pair is proposed only if similarity >= threshold AND it beats the
     runner-up for either track by at least `margin` (ambiguous matches are rejected, not guessed).
Output carries similarity, margin and the gating facts, and the label "candidate association". No claim of identity is ever made.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Sequence
import numpy as np
from scipy.optimize import linear_sum_assignment

LABEL = "candidate association: appearance similarity plus plausible timing. Not an identification."


@dataclass
class Tracklet:
    camera: str
    track_id: int
    class_name: str
    start_s: float            # on the shared clock
    end_s: float
    descriptor: np.ndarray    # L2-normalised
    identity: str | None = None   # ground truth, only for evaluation; never read by the associator

    @property
    def key(self) -> tuple[str, int]:
        return (self.camera, self.track_id)


@dataclass
class Params:
    min_gap_s: float = 0.0
    max_gap_s: float = 60.0
    # Defaults chosen from real-footage evidence (docs/evidence/crosscam-eval.json): with generic CLIP crop embeddings, 0.85 falsely links 57% of co-visible
    # DIFFERENT people (pedestrian clip) and 0.90 still links 29%; only about 0.95 gets that near 4%, at the price of almost no recall. Appearance alone is
    # therefore NOT a basis for linking: the high default makes the tool propose very little rather than guess.
    threshold: float = 0.95
    margin: float = 0.03
    same_class_only: bool = True


@dataclass
class Association:
    a: Tracklet
    b: Tracklet
    similarity: float
    margin: float
    gap_s: float
    note: str = field(default=LABEL)


def gate(a: Tracklet, b: Tracklet, p: Params) -> bool:
    if a.camera == b.camera:
        return False
    if p.same_class_only and a.class_name != b.class_name:
        return False
    gap = b.start_s - a.end_s
    return p.min_gap_s <= gap <= p.max_gap_s


def associate(a_tracks: Sequence[Tracklet], b_tracks: Sequence[Tracklet], p: Params = Params()) -> list[Association]:
    """Propose candidate links from camera-A-side tracklets to camera-B-side tracklets (A ends first)."""
    if not a_tracks or not b_tracks:
        return []
    S = np.full((len(a_tracks), len(b_tracks)), -np.inf)
    for i, a in enumerate(a_tracks):
        for j, b in enumerate(b_tracks):
            if gate(a, b, p):
                S[i, j] = float(np.dot(a.descriptor, b.descriptor))
    if not np.isfinite(S).any():
        return []
    cost = np.where(np.isfinite(S), 1.0 - S, 1e6)
    rows, cols = linear_sum_assignment(cost)
    out: list[Association] = []
    for i, j in zip(rows, cols):
        if not np.isfinite(S[i, j]) or S[i, j] < p.threshold:
            continue
        row = np.sort(S[i][np.isfinite(S[i])])[::-1]; col = np.sort(S[:, j][np.isfinite(S[:, j])])[::-1]
        run_up = max(row[1] if len(row) > 1 else -np.inf, col[1] if len(col) > 1 else -np.inf)       # best competing similarity for either track
        m = S[i, j] - run_up if np.isfinite(run_up) else float("inf")
        if m < p.margin:
            continue                                                                                   # ambiguous: refuse rather than guess
        out.append(Association(a_tracks[i], b_tracks[j], round(float(S[i, j]), 4), round(float(m), 4) if np.isfinite(m) else float("inf"), round(b_tracks[j].start_s - a_tracks[i].end_s, 3)))
    return sorted(out, key=lambda x: -x.similarity)


# ---------------- evaluation against known identities ----------------
def evaluate(assocs: Sequence[Association], a_tracks: Sequence[Tracklet], b_tracks: Sequence[Tracklet]) -> dict:
    """Needs ground-truth identities. Reports proposed-pair precision, recall of true pairs that were gate-feasible, and the wrong-association rate."""
    correct = sum(1 for x in assocs if x.a.identity is not None and x.a.identity == x.b.identity)
    wrong = len(assocs) - correct
    truth = {(a.key, b.key) for a in a_tracks for b in b_tracks if a.identity and a.identity == b.identity}
    found = {(x.a.key, x.b.key) for x in assocs}
    return {"proposed": len(assocs), "correct": correct, "wrong": wrong, "wrong_association_rate": (wrong / len(assocs)) if assocs else None,
            "true_pairs": len(truth), "recall": (len(found & truth) / len(truth)) if truth else None}


def chain_identity_switches(assocs_ab: Sequence[Association], assocs_bc: Sequence[Association]) -> dict:
    """Follow A->B->C links. A chain 'switches identity' when its tracklets do not all share one ground-truth identity."""
    nxt = {x.a.key: x for x in assocs_bc}          # a B->C link is keyed by its B-side track
    chains = switches = 0
    for x in assocs_ab:
        y = nxt.get(x.b.key)
        if y is None:
            continue
        chains += 1
        if len({x.a.identity, x.b.identity, y.b.identity}) > 1:
            switches += 1
    return {"chains": chains, "identity_switches": switches}
