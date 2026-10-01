"""cutdeck/topic_speakers.py — host vs other speaker (docs/DESIGN_TOPIC_CUT.md).

The pure parts run always. The real-episode check is opt-in (TOPIC_CUT_REAL=1, about 25 s) and needs
the 4.5 GB recording, speechbrain and a GPU. It enrols the host on 30-90 s of the HKS Facebook 290969 episode,
then scores stretches whose on-screen speaker is seen in the frames (host alone at the desk /
one guest alone in close-up). Those labels are rough: the director may show a listener.

Run: python -m pytest tests/test_cutdeck_topic_speakers.py -v
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from cutdeck.topic_speakers import (  # noqa: E402
    HOP_S, WINDOW_S, Turn, host_scores, smooth, turns_from_scores,
)

VIDEO = Path(r"E:\Me\7.test folder\Copied_20260929 - โหนกระแส\HKS Facebook 290969 Full.mp4")


def _starts(n):
    return np.arange(n) * HOP_S


def test_consecutive_windows_merge_into_one_turn():
    t = _starts(4)
    assert turns_from_scores(t, np.array([.9, .8, .9, .7])) == [Turn(0.0, 3 * HOP_S + WINDOW_S, True)]


def test_speaker_change_is_placed_inside_the_overlap():
    t = _starts(4)
    turns = turns_from_scores(t, np.array([.9, .9, .1, .1]))
    assert [x.is_host for x in turns] == [True, False]
    assert turns[0].end_s == turns[1].start_s  # no gap and no overlap between turns
    assert HOP_S * 2 <= turns[0].end_s <= HOP_S * 1 + WINDOW_S


def test_a_pause_starts_a_new_turn_even_for_the_same_speaker():
    turns = turns_from_scores(np.array([0.0, 10.0]), np.array([.9, .9]))
    assert len(turns) == 2 and all(x.is_host for x in turns)


def test_smoothing_removes_a_single_outlier():
    t = _starts(9)
    s = np.array([.8] * 9)
    s[4] = .0
    assert smooth(t, s)[4] > .5


def test_host_scores_rejects_a_sample_with_no_speech():
    with pytest.raises(ValueError):
        host_scores(_starts(3), np.eye(3), (100.0, 200.0))


def _real_run():
    import soundfile as sf
    from cutdeck.topic_speakers import host_turns

    with tempfile.TemporaryDirectory() as d:
        wav = Path(d) / "ep.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(VIDEO), "-vn", "-ac", "1", "-ar",
                        "16000", str(wav)], check=True)
        audio, _ = sf.read(wav, dtype="float32")
    return host_turns(audio, (30.0, 90.0))


def _host_share(turns, spans):
    """Fraction of the speech inside ``spans`` that the turns call the host."""
    hit = total = 0.0
    for a, b in spans:
        for t in turns:
            o = max(0.0, min(b, t.end_s) - max(a, t.start_s))
            total += o
            hit += o if t.is_host else 0.0
    return hit / total


@pytest.mark.skipif(
    os.environ.get("TOPIC_CUT_REAL") != "1" or not (VIDEO.exists() and shutil.which("ffmpeg")),
    reason="opt-in (slow): set TOPIC_CUT_REAL=1 and have the episode video",
)
def test_separates_host_from_guests_on_the_real_episode():
    pytest.importorskip("speechbrain")
    turns = _real_run()
    host = _host_share(turns, [(90, 150), (2460, 2500), (2530, 2545)])  # host alone on screen
    guest = _host_share(turns, [(870, 960), (2850, 2880), (3000, 3010), (3120, 3130), (3240, 3260)])
    assert host >= 0.85, host
    assert guest <= 0.15, guest
