"""Legal uncovered cut points (cutdeck/hks_cutpoints.py, build plan step 2.5): the pure detector
parts on built frames, then the real punch-in and a real camera change when the G: drive is
mounted."""

import json
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from cutdeck import hks_cutpoints as cp

FOOTAGE = Path(r"G:\Me\Works\20261120 - โหนกระแส\1. FOOTAGE\HKS Facebook 201169 Full.mp4")
RNG = np.random.default_rng(7)


def test_cache_key_distinguishes_footage_and_invalidates_when_modified(tmp_path):
    first = tmp_path / "episode1" / "camera.mp4"
    second = tmp_path / "episode2" / "camera.mp4"
    for path, content in [(first, b"old"), (second, b"new")]:
        path.parent.mkdir()
        path.write_bytes(content)
    stamp = first.stat()
    os.utime(second, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))

    key = cp._key(first)
    assert key != cp._key(second)
    first.write_bytes(b"new")
    os.utime(first, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 2_000_000_000))
    assert key != cp._key(first)


def texture(h=90, w=160) -> np.ndarray:
    """A smooth random grey picture as RGB, about as smooth as a 160x90 video frame."""
    small = RNG.integers(0, 256, (h // 10, w // 10)).astype(np.uint8)
    g = np.asarray(Image.fromarray(small).resize((w, h), Image.BICUBIC))
    return np.stack([g] * 3, -1)


def zoom(rgb: np.ndarray, k: float) -> np.ndarray:
    """A punch-in: the centre 1/k of the frame scaled back to full size."""
    h, w = rgb.shape[:2]
    ch, cw = round(h / k), round(w / k)
    y, x = (h - ch) // 2, (w - cw) // 2
    return np.asarray(Image.fromarray(rgb[y:y + ch, x:x + cw]).resize((w, h), Image.BILINEAR))


def test_a_hard_cut_is_one_candidate_and_slow_motion_is_none():
    a, b = texture(36, 64)[..., 0], texture(36, 64)[..., 0]
    drift = [np.roll(a, k, axis=1) for k in range(12)]  # a pan: every frame moves alike, never abrupt
    thumbs = np.stack(drift + [np.roll(b, k, axis=1) for k in range(12)])
    found = cp.candidates(thumbs)
    assert [i for i, _ in found] == [12]
    assert found[0][1].mean() >= cp.FULL_FRAME


def test_inset_boxes_are_learned_from_repeats_only():
    m = np.zeros((36, 64), bool)
    inset = m.copy()
    inset[10:26, 38:64] = True
    once = m.copy()
    once[2:20, 2:20] = True
    strip = m.copy()
    strip[0:3, 30:64] = True  # the background loop's band: repeats, but is no picture
    cands = ([(i, inset) for i in range(cp.BOX_MIN_SEEN)] + [(99, once)] * (cp.BOX_MIN_SEEN - 1)
             + [(98, strip)] * cp.BOX_MIN_SEEN)
    assert cp.inset_boxes(cands) == [(38, 10, 63, 25)]


def test_same_shot_tells_a_punch_in_from_another_camera():
    a = texture()
    assert cp.same_shot(a, zoom(a, 1.5)) >= cp.SAME_SHOT
    assert cp.same_shot(zoom(a, 2.5), a) >= cp.SAME_SHOT
    assert cp.same_shot(a, texture()) < cp.SAME_SHOT


def test_classify_routes_by_layout_and_change():
    boxes = [(38, 10, 63, 25)]
    studio_a, studio_b = texture(), texture()
    full = np.ones((36, 64), bool)
    assert cp.classify(full, lambda: (studio_a, studio_b), boxes) == "camera"
    assert cp.classify(full, lambda: (studio_a, zoom(studio_a, 1.33)), boxes) is None  # punch-in

    def clip(rgb):  # the news-clip layout: the show's blue frame around a window
        out = np.zeros_like(rgb)
        out[...] = (20, 60, 220)
        out[10:70, 10:150] = rgb[10:70, 10:150]
        return out
    in_box = np.zeros((36, 64), bool)
    in_box[10:26, 38:64] = True
    assert cp.classify(in_box, lambda: (clip(studio_a), clip(studio_b)), boxes) == "inset"
    elsewhere = np.zeros((36, 64), bool)
    elsewhere[5:30, 2:30] = True  # the big window cuts, the inset stays
    assert cp.classify(elsewhere, lambda: pytest.fail("frames not needed"), boxes) is None


def test_still_runs_allow_a_ticking_clock_but_not_motion():
    pic = texture(36, 64)[..., 0]
    frames = []
    for k in range(100):  # 4 s of one picture at 25 fps; the "clock" corner ticks every second
        f = pic.copy()
        f[0:2, 0:6] = (k // 25) * 40
        frames.append(f)
    frames += [np.roll(pic, k, axis=1) for k in range(1, 50)]  # then a pan
    runs = cp.still_runs(np.stack(frames), 25.0)
    assert runs == [(0, 100)]


def test_still_runs_split_at_a_hard_cut_and_merge_over_a_flash():
    a, b = texture(36, 64)[..., 0], texture(36, 64)[..., 0]
    assert cp.still_runs(np.stack([a] * 50 + [b] * 50), 25.0) == [(0, 50), (50, 100)]
    flash = [a] * 40 + [b] * 5 + [a] * 55  # an overlay for 0.2 s over one still picture
    assert cp.still_runs(np.stack(flash), 25.0) == [(0, 100)]


def test_points_section_and_matching():
    p = cp.Points(camera=[10.0], inset=[20.04], still=[(30.0, 33.0)])
    assert p.section() == [[10.0, "camera"], [20.04, "inset"], [30.0, 33.0, "still"]]
    assert p.near(10.1) == "camera" and p.near(19.94) == "inset" and p.near(31.5) == "still"
    assert p.near(10.2) is None and p.near(33.2) is None


def test_audit_keeps_same_named_footage_separate_by_episode():
    points = {("20261119", "camera.mp4"): cp.Points(camera=[10], inset=[], still=[]),
              ("20261120", "camera.mp4"): cp.Points(camera=[], inset=[], still=[])}
    row = {"day": "20261119", "before": ("Camera.mp4", 10), "after": ("Camera.mp4", 20)}
    assert cp.explained(row, points) == "camera"
    assert cp.explained({**row, "day": "20261120"}, points) is None


def test_hand_labels_are_inside_their_stretch_and_unique():
    labels = json.loads(cp.LABELS.read_text(encoding="utf-8"))
    legal = [t for kind in ("camera", "inset") for t in labels["legal"][kind]]
    assert len(legal) == len(set(legal)) and len(legal) >= 50
    assert all(any(a <= t < b for a, b in labels["stretch"]) for t in legal)
    assert sum(b - a for a, b in labels["stretch"]) == pytest.approx(600)


@pytest.mark.skipif(not FOOTAGE.exists(), reason="needs the G: footage")
def test_the_real_punch_in_is_one_shot_and_a_real_camera_change_is_not():
    # tl 681.92 joins source 2518.68 and 2520.16. The field camera punches in at 2518.64 (frame
    # 62966), the last frame the cut keeps (rule-audit.md: a punch-in, not legal). Both the source
    # change and the two frames the cut joins must read as one shot.
    sc = cp.scan(FOOTAGE)
    wide, tight = cp._grab_pair(FOOTAGE, 62966, sc)
    assert cp.same_shot(wide, tight) >= cp.SAME_SHOT
    after = cp._grab_pair(FOOTAGE, round(2520.16 * 25), sc)[1]  # the frame the cut jumps to
    assert cp.same_shot(tight, after) >= cp.SAME_SHOT
    a, b = cp._grab_pair(FOOTAGE, round(708.76 * 25), sc)  # studio close-up to the wide shot
    assert cp.same_shot(a, b) < cp.SAME_SHOT
