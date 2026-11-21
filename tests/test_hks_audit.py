"""HKS rule audit (cutdeck/hks_audit.py): the pure parts on synthetic data, then the camera-change
test on the real day folders when the G: drive is mounted."""

from pathlib import Path

import numpy as np
import pytest

from cutdeck.hks_audit import (CAMERA_CHANGE, FRAME, HALF, Layer, blur_samples, blurred_at, dips,
                               frame_diff, is_camera_change, latest_export, layers, main_framing,
                               picture_at, placed, runs, spans_of, tv_part)

MAIN = (1920, (0.5, 0.5), False)
ZOOM = (5550, (0.78, 0.682), False)


def layer(track, start, end, kind="footage", *, source_in=0.0, framing=MAIN, blur=False, media="show.mp4"):
    return Layer(track, start, end, kind, media, media, source_in, framing, blur)


def test_frame_diff_separates_a_new_picture_from_the_same_one():
    rng = np.random.default_rng(0)
    shot = rng.integers(0, 256, (72, 128, 3), dtype=np.uint8)
    noisy = np.clip(shot.astype(int) + rng.integers(-3, 4, shot.shape), 0, 255).astype(np.uint8)
    other = rng.integers(0, 256, (72, 128, 3), dtype=np.uint8)
    assert frame_diff(shot, shot) == 0
    assert not is_camera_change(frame_diff(shot, noisy))
    assert is_camera_change(frame_diff(shot, other))
    assert is_camera_change(CAMERA_CHANGE) and not is_camera_change(CAMERA_CHANGE - 0.01)


def test_runs_and_dips_inside_the_tv_part():
    #        head  TV on 0-39, 12 s off, 3 s off, TV on   social with a 1 s false clock
    clock = [0] * 5 + [1] * 35 + [0] * 12 + [1] * 40 + [0] * 3 + [1] * 30 + [0] * 20 + [1] + [0] * 9
    assert runs([1, 1, 0, 1], True) == [(0, 2), (3, 4)]
    assert runs([1, 1, 0, 1], True, min_len=2) == [(0, 2)]
    part = tv_part(clock)
    assert part == (5, 125)               # ends with the last run of 30 s or more, not the 1 s blip
    assert dips(clock, part) == [(40, 52)]  # the 3 s gap is not a dip
    assert tv_part([0, 1, 1, 0]) is None


def test_picture_is_the_topmost_footage_or_hold_and_overlays_are_skipped():
    ls = [layer(9, 0, 100, "other", blur=True),         # blur adjustment layer
          layer(5, 40, 60, "other"),                    # film damage overlay
          layer(2, 20, 30, "hold", media="CutDeck_Hold_1.png"),
          layer(1, 10, 50, source_in=500, framing=ZOOM),
          layer(0, 0, 100)]
    ls.sort(key=lambda l: -l.track)
    assert picture_at(ls, 5).track == 0
    assert picture_at(ls, 15).track == 1 and picture_at(ls, 15).source_at(15) == 505
    assert Layer(1, 10, 50, "footage", "show.mp4", "show.mp4", 500, MAIN, False, 498.0).source_at(15) == 498
    assert picture_at(ls, 25).kind == "hold"
    assert picture_at(ls, 45).track == 1
    assert picture_at(ls, 100) is None


def test_an_adjustment_layer_blurs_only_the_tracks_below_it():
    ls = [layer(4, 0, 10), layer(3, 0, 20, "other", blur=True), layer(0, 0, 20)]
    assert not blurred_at(ls, 5, 4)
    assert blurred_at(ls, 5, 0)
    assert blurred_at(ls, 15, 0) and not blurred_at(ls, 25, 0)
    assert blurred_at([layer(0, 0, 10, blur=True)], 5, 0)  # blur on the clip itself


def test_blur_samples_classify_clock_zoom_and_blur():
    # 0-10 main shot blurred, 10-20 main shot not blurred, 20-30 zoomed insert under the blur,
    # 30-40 main shot from a clock-free source time.
    ls = [layer(8, 0, 10, "other", blur=True), layer(8, 20, 30, "other", blur=True),
          layer(1, 20, 30, framing=ZOOM), layer(0, 0, 40)]
    clock_of = lambda l, t: l.source_at(t) < 30
    rows = blur_samples(ls, clock_of, 0, 40)
    assert main_framing(ls, 0, 40) == MAIN
    states = [(r["state"], r["blurred"]) for r in rows]
    assert states == [("clock", True)] * 10 + [("clock", False)] * 10 + [("zoomed", True)] * 10 + \
        [("no-clock", False)] * 10
    assert spans_of([r["t"] for r in rows if r["state"] == "clock" and not r["blurred"]]) == [(10, 20)]


def test_placed_applies_motion_scale_and_position():
    frame = np.zeros((72, 128, 3), np.uint8)
    frame[18:54, 32:96] = 255                                  # the central quarter is white
    assert (placed(frame, (1920, (0.5, 0.5), False), 1920) == frame).all()
    zoomed = placed(frame, (3840, (0.5, 0.5), False), 1920)    # 200 % centred: white but the smoothed rim
    assert zoomed[2:-2, 2:-2].min() == 255
    moved = placed(frame, (1920, (1.0, 0.5), False), 1920)     # centre on the right edge
    assert moved[36, 98:].min() == 255 and moved[:, :64].max() == 0


def test_latest_export_takes_the_highest_take(tmp_path):
    exports = tmp_path / "5. EXPORTS"
    exports.mkdir()
    for name in ("x YT D1.mp4", "x YT D2.mp4", "x REEL FB D1.mp4", "x REEL 1M D1.mp4", "x REEL 3M D3.mp4"):
        (exports / name).touch()
    assert latest_export(tmp_path, "YT").name == "x YT D2.mp4"
    assert latest_export(tmp_path, "FB").name == "x REEL FB D1.mp4"
    assert latest_export(tmp_path, "REEL 1M").name == "x REEL 1M D1.mp4"
    assert latest_export(tmp_path, "SQUARE") is None


# --- real day folders ----------------------------------------------------------------------------

WORKS = Path("G:/Me/Works")
DAY_1120 = WORKS / "20261120 - โหนกระแส"


@pytest.mark.skipif(not DAY_1120.exists(), reason="G: drive with the HKS day folders not mounted")
@pytest.mark.parametrize("before, after, change", [
    (312.60, 321.40, True),    # close-up -> two-shot (hand-checked 2026-11-20)
    (2524.84, 2525.40, False),  # the 0.56 s same-shot cut
    (2526.40, 2528.00, False),  # the 1.6 s same-shot cut
])
def test_camera_change_on_20261120(before, after, change):
    from cutdeck.hks_audit import grab_frame
    footage = str(DAY_1120 / "1. FOOTAGE" / "HKS Facebook 201169 Full.mp4")
    diff = frame_diff(grab_frame(footage, before - 1.5 * FRAME), grab_frame(footage, after - HALF))
    assert is_camera_change(diff) is change

