"""cutdeck.prproj_anchor_check: the read-back for the Transform panel's live gates."""

import copy
import math

import pytest

from cutdeck import prproj_anchor_check as chk

FRAME = [1920, 1080]
SRC = [1280, 720]
CROP = {"crop_left": 10.0, "crop_top": 20.0, "crop_right": 30.0, "crop_bottom": 40.0}


def _seq(scale, scale_width, uniform, rotation, anchor=(0.5, 0.5), position=(0.5, 0.5)):
    params = {"position": {"value": list(position)}, "scale": {"value": scale}, "scale_width": {"value": scale_width},
              "uniform": {"value": uniform}, "rotation": {"value": rotation}, "anchor": {"value": list(anchor)},
              **{k: {"value": v} for k, v in CROP.items()}}
    clip = {"name": "c", "start": 1.0, "source_frame": SRC,
            "effects": [{"match_name": "AE.ADBE Motion", "params": params}]}
    return {"frame": FRAME, "video_tracks": [{"index": 0, "clips": [clip]}]}


def _move_anchor(seq, target):
    """What the panel writes: anchor to the target on the visible rect, Position compensated."""
    out = copy.deepcopy(seq)
    m = chk.motion_model(out["video_tracks"][0]["clips"][0], FRAME)
    (fx, fy), = [k for k, v in chk.TARGETS.items() if v == target]
    l, t, r, b = m["rect"]
    ax, ay = l + fx * (r - l), t + fy * (b - t)
    px, py = chk.to_sequence(m, ax, ay)  # the source point moves to the anchor; Position = where it is drawn now
    p = out["video_tracks"][0]["clips"][0]["effects"][0]["params"]
    p["anchor"]["value"] = [ax / SRC[0], ay / SRC[1]]
    p["position"]["value"] = [px / FRAME[0], py / FRAME[1]]
    return out


@pytest.mark.parametrize("scale,width,uniform", [(100.0, 100.0, True), (50.0, 80.0, False)])
@pytest.mark.parametrize("rotation", [0.0, 90.0, 15.0])
@pytest.mark.parametrize("target", sorted(chk.TARGETS.values()))
def test_compensated_anchor_move_moves_nothing_and_lands_on_the_target(scale, width, uniform, rotation, target):
    before = _seq(scale, width, uniform, rotation, anchor=(0.3, 0.6), position=(0.4, 0.55))
    rows = chk.compare(before, _move_anchor(before, target))
    assert rows[0]["anchor"] == target
    assert rows[0]["drift"] < 1e-6


def test_an_uncompensated_anchor_move_shows_up_as_drift():
    before = _seq(50.0, 80.0, False, 15.0)
    after = copy.deepcopy(before)
    after["video_tracks"][0]["clips"][0]["effects"][0]["params"]["anchor"]["value"] = [0.0, 0.0]
    assert chk.compare(before, after)[0]["drift"] > 10


def test_uniform_off_reads_scale_as_height_and_scale_width_as_width():
    m = chk.motion_model(_seq(50.0, 80.0, False, 0.0)["video_tracks"][0]["clips"][0], FRAME)
    assert (m["scale"], m["scale_h"]) == (0.8, 0.5)


def test_positive_rotation_is_clockwise_on_screen():
    m = chk.motion_model(_seq(100.0, 100.0, True, 90.0, anchor=(0, 0), position=(0, 0))["video_tracks"][0]["clips"][0], FRAME)
    x, y = chk.to_sequence(m, 100, 0)
    assert math.isclose(x, 0, abs_tol=1e-9) and math.isclose(y, 100)
