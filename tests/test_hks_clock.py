"""cutdeck.hks_clock: the TV clock test on committed crops, and on the real 20261120 footage
when that drive is mounted."""

import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from cutdeck.hks_clock import (CROP_H, CROP_W, CROP_X, CROP_Y, clock_fraction, clock_in_frame,
                               clock_samples, grab_crop)

FIXTURES = Path(__file__).parent / "fixtures" / "hks_clock"
FOOTAGE_1120 = Path("G:/Me/Works/20261120 - โหนกระแส/1. FOOTAGE/HKS Facebook 201169 Full.mp4")


def _crop(name: str) -> np.ndarray:
    return np.asarray(Image.open(FIXTURES / name).convert("RGB"))


@pytest.mark.parametrize("name, on", [
    ("present_dark.png", True),     # 20261120 @ 30 s, 12:35:26 on the blue studio
    ("present_bright.png", True),   # 20261112 (1) @ 1560 s: over a white band, weakest seen (69)
    ("absent_wall.png", False),     # 20261120 @ 2034 s: white wall lights the colon pixels
    ("absent_graphic.png", False),  # 20261001 @ 300 s: a yellow graphic, no clock
])
def test_clock_in_frame_on_fixtures(name, on):
    assert clock_in_frame(_crop(name)) is on


def test_clock_fraction_on_a_built_video(tmp_path):
    # 2 s with the clock, then 2 s of bright wall, as a 1280x720 video.
    stills = []
    for name in ("present_dark.png", "absent_wall.png"):
        frame = np.full((720, 1280, 3), 30, np.uint8)
        frame[CROP_Y:CROP_Y + CROP_H, CROP_X:CROP_X + CROP_W] = _crop(name)
        stills.append(tmp_path / name)
        Image.fromarray(frame).save(stills[-1])
    video = tmp_path / "v.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-loop", "1", "-t", "2", "-i", str(stills[0]),
         "-loop", "1", "-t", "2", "-i", str(stills[1]), "-filter_complex", "concat=n=2",
         "-r", "10", "-pix_fmt", "yuv444p", "-crf", "1", str(video)], check=True)
    assert clock_samples(str(video), step_s=1.5) == [(0.0, True), (1.5, True), (3.0, False)]
    assert clock_fraction(str(video), step_s=1.5) == pytest.approx(2 / 3)


def test_clock_in_frame_rejects_a_full_frame():
    with pytest.raises(ValueError):
        clock_in_frame(np.zeros((720, 1280, 3), np.uint8))


real = pytest.mark.skipif(not FOOTAGE_1120.exists(), reason="20261120 footage not mounted")


@real
@pytest.mark.parametrize("t, on", [(30, True), (2815, True), (2825, False), (3000, False)])
def test_clock_on_real_footage(t, on):
    assert clock_in_frame(grab_crop(str(FOOTAGE_1120), t)) is on


@real
def test_clock_turns_off_once_between_2815_and_2825():
    window = [(t, clock_in_frame(grab_crop(str(FOOTAGE_1120), t))) for t in range(2700, 2951, 5)]
    edges = [b[0] for a, b in zip(window, window[1:]) if a[1] != b[1]]
    assert len(edges) == 1 and 2815 < edges[0] <= 2825
