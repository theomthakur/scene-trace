"""Timestamps, rotation and probe behaviour on small generated videos (needs ffmpeg and PyAV; skipped if ffmpeg is absent)."""
import shutil, subprocess
from fractions import Fraction
import av, numpy as np, pytest
from video_investigator.media.decode import iter_samples
from video_investigator.media.probe import MediaError, probe, validate_limits

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def make_video(path, pts_ms, size=(160, 96), rotate=None, marker=True):
    """Write a video with explicit presentation times (ms). Frame k has a red square in the top-left of the CODED frame."""
    with av.open(str(path), "w") as c:
        s = c.add_stream("libx264", rate=25); s.width, s.height, s.pix_fmt = size[0], size[1], "yuv420p"; s.time_base = Fraction(1, 1000); s.codec_context.time_base = Fraction(1, 1000)   # keep ms pts through the encoder
        for k, ms in enumerate(pts_ms):
            img = np.full((size[1], size[0], 3), 40, np.uint8)
            if marker:
                img[:24, :24] = (255, 0, 0)
            img[:, -6:, 1] = (k * 7) % 255          # per-frame green stripe so frames differ
            f = av.VideoFrame.from_ndarray(img, format="rgb24"); f.pts = ms; f.time_base = Fraction(1, 1000)
            for p in s.encode(f):
                c.mux(p)
        for p in s.encode():
            c.mux(p)
    if rotate:
        tmp = path.with_suffix(".rot.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-display_rotation", str(rotate), "-i", str(path), "-c", "copy", str(tmp)], check=True)
        tmp.replace(path)


def test_variable_presentation_intervals_are_sampled_by_time(tmp_path):
    pts = [0, 40, 80, 400, 440, 500, 900, 1000, 1040, 1500, 2000, 2040]
    v = tmp_path / "vfr.mkv"; make_video(v, pts)
    info = probe(v)
    got = [f.t_ms for f in iter_samples(v, info, 5.0, 960)]
    # Sample instants advance by 200 ms: 0 -> frame 0; next 200 -> first frame >= 200 is 400 (next becomes 600); 440 and 500 are before 600 and
    # skipped; 900 -> next becomes 1000; 1000 qualifies; 1500 -> next 1600; 2000 qualifies. Frame count never enters the rule.
    assert got == [0, 400, 900, 1000, 1500, 2000], got
    assert all(b > a for a, b in zip(got, got[1:]))


def test_rotation_probe_and_decode_orientation(tmp_path):
    v = tmp_path / "rot.mp4"; make_video(v, list(range(0, 400, 40)), size=(160, 96), rotate=90)
    info = probe(v)
    assert info.rotation in (90, 270) and (info.width, info.height) == (96, 160) and (info.coded_width, info.coded_height) == (160, 96)
    fr = next(iter(iter_samples(v, info, 5.0, 960)))
    assert fr.image.shape[:2] == (160, 96)
    red = np.argwhere((fr.image[:, :, 0] > 200) & (fr.image[:, :, 1] < 80))
    cy, cx = red.mean(axis=0)
    # The marker is at the coded top-left. After upright orientation it must be in a corner consistent with the rotation direction:
    # 90 degrees clockwise puts coded top-left at display top-right; 270 puts it at display bottom-left.
    if info.rotation == 90:
        assert cx > 48 and cy < 80
    else:
        assert cx < 48 and cy > 80


def test_resize_bounds_long_edge(tmp_path):
    v = tmp_path / "big.mp4"; make_video(v, list(range(0, 400, 40)), size=(640, 360))
    info = probe(v)
    fr = next(iter(iter_samples(v, info, 5.0, 320)))
    assert max(fr.image.shape[:2]) == 320 and abs(fr.image.shape[1] / fr.image.shape[0] - 640 / 360) < 0.02


def test_non_video_and_corrupt_and_missing_have_explicit_codes(tmp_path):
    txt = tmp_path / "fake.mp4"; txt.write_text("not a video")
    with pytest.raises(MediaError) as e:
        probe(txt)
    assert e.value.code == "not_a_video"
    with pytest.raises(MediaError) as e:
        probe(tmp_path / "missing.mp4")
    assert e.value.code == "not_found"
    v = tmp_path / "ok.mp4"; make_video(v, list(range(0, 400, 40)))
    trunc = tmp_path / "trunc.mp4"; trunc.write_bytes(v.read_bytes()[:200])
    with pytest.raises(MediaError):
        probe(trunc)


def test_limits_are_enforced_with_codes(tmp_path):
    v = tmp_path / "ok.mp4"; make_video(v, list(range(0, 4000, 40)))
    info = probe(v)
    with pytest.raises(MediaError) as e:
        validate_limits(info, max_bytes=100, max_seconds=300)
    assert e.value.code == "too_large"
    with pytest.raises(MediaError) as e:
        validate_limits(info, max_bytes=10**9, max_seconds=1)
    assert e.value.code == "too_long"
