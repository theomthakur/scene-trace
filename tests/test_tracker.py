import numpy as np
from video_investigator.vision.detector import Detection
from video_investigator.vision.tracker import Tracker, iou_matrix


def det(cls, box, cid=None, score=0.9):
    return Detection({"person": 1, "car": 3}.get(cls, 0) if cid is None else cid, cls, score, box)


def make(**kw):
    return Tracker(iou_gate=kw.get("gate", 0.2), max_missing_s=kw.get("missing", 1.0), min_hits=kw.get("hits", 2), smoothing=0.5)


def test_empty_frames_and_empty_matrices():
    t = make()
    assert t.update(0, []) == [] and t.update(200, []) == []
    assert iou_matrix(np.zeros((0, 4)), np.zeros((3, 4))).shape == (0, 3)


def test_new_object_confirms_after_min_hits_and_keeps_id():
    t = make()
    a = t.update(0, [det("person", (0.1, 0.1, 0.2, 0.4))])[0]
    b = t.update(200, [det("person", (0.11, 0.1, 0.21, 0.4))])[0]
    assert a.track_id == b.track_id and a.track_state == "tentative" and b.track_state == "confirmed"


def test_class_mismatch_never_matches():
    t = make()
    t.update(0, [det("person", (0.1, 0.1, 0.3, 0.5))])
    o = t.update(200, [det("car", (0.1, 0.1, 0.3, 0.5))])[0]
    assert o.track_id == 2


def test_occlusion_within_lifetime_keeps_id_and_beyond_gets_new_id_never_recycled():
    t = make()
    first = t.update(0, [det("person", (0.1, 0.1, 0.2, 0.4))])[0].track_id
    t.update(200, [det("person", (0.1, 0.1, 0.2, 0.4))])
    back = t.update(800, [det("person", (0.1, 0.1, 0.2, 0.4))])[0]          # missing 0.6 s < 1.0 s
    assert back.track_id == first
    far = t.update(3000, [det("person", (0.1, 0.1, 0.2, 0.4))])[0]          # missing 2.2 s > 1.0 s: ended, new identity
    assert far.track_id != first and far.track_id > first


def test_crossing_objects_keep_identities_with_velocity_prediction():
    t = make(gate=0.1)
    ids = {}
    for k in range(11):
        x = 0.05 * k
        out = t.update(k * 200, [det("person", (0.1 + x, 0.2, 0.2 + x, 0.5)), det("person", (0.6 - x, 0.22, 0.7 - x, 0.52))])
        if k == 0:
            ids = {0: out[0].track_id, 1: out[1].track_id}
    assert out[0].track_id == ids[0] and out[1].track_id == ids[1]


def test_assignment_beyond_the_gate_is_rejected():
    t = make(gate=0.5)
    t.update(0, [det("person", (0.1, 0.1, 0.2, 0.3))])
    o = t.update(200, [det("person", (0.15, 0.1, 0.25, 0.3))])[0]       # IoU 1/3 < 0.5 gate
    assert o.track_id == 2
