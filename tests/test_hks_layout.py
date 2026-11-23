"""cutdeck/hks_layout.py: the picture layout per second (HKS build plan step 2.4).

Synthetic frames always run. The real-data tests read the hand-labelled tuning frames of
tests/data/hks_layout_labels.json from the footage on G: (about 2 min of ffmpeg seeks) and are
skipped when it is absent. The holdout labels are not read here: they are scored once, by
``python -m cutdeck.hks_layout --all G:\\Me\\Works --check --holdout``.

Run: python -m pytest tests/test_hks_layout.py -v
"""
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from cutdeck.hks_layout import (BUMPER, CCTV, CLIP, FOOTAGE, LABELS, STUDIO, kind_of, kinds,  # noqa: E402
                                measure, merged)

ROOT = Path(r"G:\Me\Works")
BLUE, RED, GREY = (30, 90, 230), (200, 30, 40), (110, 105, 100)


def _kind(frame):
    return kind_of(*measure(frame[None])[0])


def _frame(colour=GREY):
    return np.full((180, 320, 3), colour, np.uint8)


def test_blue_frame_under_the_ticker_is_clip():
    f = _frame()
    f[140:] = BLUE
    assert _kind(f) == CLIP


def test_set_panels_are_studio():
    f = _frame()
    f[:140, :40] = BLUE  # 12.5 % of the picture above the ticker
    assert _kind(f) == STUDIO


def test_red_wall_is_studio():
    f = _frame()
    f[20:100, 160:] = RED
    assert _kind(f) == STUDIO


def test_picture_without_the_set_colours_is_footage():
    f = _frame()
    f[:140, :10] = BLUE  # a little blue, as a sky or a logo
    assert _kind(f) == FOOTAGE


def test_drop_seconds_are_bumper_and_runs_merge():
    m = np.array([[0.5, 0.2, 0.0]] * 3 + [[0.0, 0.1, 0.0]] * 4 + [[0.0, 0.0, 0.0]] * 3)
    ks = kinds(m, [{"start": 4.5, "end": 6.0, "kind": "bumper", "why": ""}])
    assert merged(ks) == [[0, 3, CLIP], [3, 5, STUDIO], [5, 6, BUMPER], [6, 7, STUDIO], [7, 10, FOOTAGE]]


def test_no_drops_reads_the_picture():
    m = np.array([[0.0, 0.0, 0.0]] * 2)
    assert kinds(m, None) == kinds(m, []) == [FOOTAGE, FOOTAGE]


# --- real data -----------------------------------------------------------------------------------

real = pytest.mark.skipif(not (ROOT.exists() and shutil.which("ffmpeg")), reason="needs the HKS footage on G:")


def _footage(day: str, file: str) -> Path:
    (folder,) = ROOT.glob(f"{day}*โหนกระแส")
    return folder / "1. FOOTAGE" / file


def _second(path: Path, t: int) -> np.ndarray:
    """The frame ``hks_layout.frames`` holds for second ``t``: the fps=1 filter picks the one at
    t + 0.48 s of this 25 fps footage."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t + 0.46:.2f}", "-i", str(path), "-frames:v", "1",
                          "-vf", "scale=320:180:flags=area", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(180, 320, 3)


@real
def test_tuning_labels_by_picture():
    rows = [r for r in json.loads(LABELS.read_text(encoding="utf-8"))["tuning"] if r["label"] != BUMPER]
    got: dict[str, Counter] = {}
    for r in rows:
        got.setdefault(r["label"], Counter())[_kind(_second(_footage(r["day"], r["file"]), r["t"]))] += 1
    acc = {k: c[k] / sum(c.values()) for k, c in got.items()}
    # measured 2026-11-23: studio 215/222, clip 132/133, footage 48/51
    assert acc[STUDIO] >= 0.95 and acc[CLIP] >= 0.98 and acc[FOOTAGE] >= 0.90, got


@real
def test_cctv_cover_reads_as_footage():
    day, a, b = CCTV
    path = _footage(day, "HKS Facebook 201169 Full.mp4")
    share = sum(_kind(_second(path, t)) == FOOTAGE for t in range(a, b)) / (b - a)
    assert share >= 0.9, share  # 100 % measured
