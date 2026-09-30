"""cutdeck/topic_layout.py — clip vs studio layout of a frame (docs/DESIGN_TOPIC_CUT.md).

Synthetic frames always run. The labelled-video check replays the 193 hand labels
(tests/data/topic_layout_labels.json, one frame per 30 s of the HKS Facebook 290969 episode) and
is opt-in (about 90 s): set TOPIC_CUT_REAL=1, and it needs that 4.5 GB recording.

Run: python -m pytest tests/test_cutdeck_topic_layout.py -v
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from cutdeck.topic_layout import CLIP, STUDIO, classify_frame  # noqa: E402

VIDEO = Path(r"E:\Me\7.test folder\Copied_20260929 - โหนกระแส\HKS Facebook 290969 Full.mp4")
LABELS = Path(__file__).parent / "data" / "topic_layout_labels.json"


def _frame(colour, edge=None):
    f = np.full((180, 320, 3), colour, np.uint8)
    if edge is not None:
        f[:12] = edge
        f[:, :10] = edge
        f[:, -10:] = edge
    return f


def test_blue_framed_footage_is_clip():
    assert classify_frame(_frame((120, 110, 100), edge=(30, 130, 210))) == CLIP


def test_dark_set_is_studio():
    assert classify_frame(_frame((90, 30, 40))) == STUDIO


def test_blue_only_on_top_is_studio():
    f = _frame((120, 110, 100))
    f[:12] = (30, 130, 210)
    assert classify_frame(f) == STUDIO


def _partly_blue(top_share):
    f = _frame((120, 110, 100))
    f[:, :10] = f[:, -10:] = (30, 130, 210)
    f[:12, : int(320 * top_share)] = (30, 130, 210)
    return f


def test_top_edge_mostly_blue_is_clip():
    assert classify_frame(_partly_blue(0.6)) == CLIP


def test_top_edge_mostly_not_blue_is_studio():
    assert classify_frame(_partly_blue(0.3)) == STUDIO


def test_works_at_other_sizes():
    f = np.full((720, 1280, 3), (120, 110, 100), np.uint8)
    f[:40] = f[:, :32] = f[:, -32:] = (30, 130, 210)
    assert classify_frame(f) == CLIP


@pytest.mark.skipif(
    os.environ.get("TOPIC_CUT_REAL") != "1" or not (VIDEO.exists() and shutil.which("ffmpeg")),
    reason="opt-in (slow): set TOPIC_CUT_REAL=1 and have the episode video",
)
def test_matches_hand_labels_on_the_real_episode():
    labels = json.loads(LABELS.read_text())["labels"]
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(VIDEO), "-an", "-vf", "fps=1/30,scale=320:180",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True,
    )
    frames = np.frombuffer(proc.stdout, np.uint8).reshape(-1, 180, 320, 3)
    assert len(frames) == len(labels)
    truth = {"S": STUDIO, "C": CLIP}
    scored = [(classify_frame(f), truth[labels[str(i * 30)]]) for i, f in enumerate(frames)
              if labels[str(i * 30)] in truth]
    acc = sum(p == t for p, t in scored) / len(scored)
    assert acc >= 0.93, acc  # 93.6% measured; the misses are full-screen footage frames
