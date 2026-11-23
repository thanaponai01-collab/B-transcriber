"""Host vs guest turns (cutdeck/hks_turns.py, HKS plan step 2.6). The check runs on the frozen hand
labels in tests/data; the real-footage run needs the G: day folders (and the GPU on a cold cache)."""

import json
from pathlib import Path

import numpy as np
import pytest

from cutdeck import hks_turns as ht

ROOT = Path(r"G:\Me\Works")
LABELS = [json.loads(p.read_text(encoding="utf-8")) for p in ht.LABELS]


def _key(lab):
    return (lab["day"], lab["file"])


def test_a_detector_that_calls_everything_host_fails_the_check():
    lines, fails = ht.check({_key(lab): [[0.0, 1e5, "host"]] for lab in LABELS}, LABELS)
    assert len(fails) == len(LABELS)  # precision, on every label set; the story-1 share is 1.0
    assert all("precision" in f for f in fails)


def test_the_labels_themselves_pass_and_set_the_story1_ceiling():
    perfect = {_key(lab): [s for s in lab["spans"] if s[2] == "host"] for lab in LABELS}
    lines, fails = ht.check(perfect, LABELS)
    assert fails == []
    assert ht.precision_recall(perfect[_key(LABELS[0])], LABELS[0]["spans"]) == (1.0, 1.0)
    assert ht.host_share(perfect[_key(LABELS[0])], ht.STORY1[1]) == pytest.approx(0.40, abs=0.01)


def test_precision_and_recall_skip_the_collar_and_unlabelled_time():
    spans = [[0.0, 2.0, "host"], [2.0, 4.0, "guest"]]
    turns = [[0.0, 2.2, "host"], [2.2, 4.0, "guest"], [10.0, 20.0, "host"]]  # 0.2 s spill, and noise off the labels
    assert ht.precision_recall(turns, spans) == (1.0, 1.0)
    p, r = ht.precision_recall([[1.0, 3.0, "host"]], spans)
    assert p == pytest.approx(0.5, abs=0.05) and r == pytest.approx(0.5, abs=0.05)


def test_host_share_counts_only_host_turns():
    assert ht.host_share([[0, 5, "host"], [5, 10, "guest"]], [(0, 10)]) == 0.5


def test_turns_follow_the_profile():
    profile = np.eye(4, dtype=np.float32)[0]
    starts = np.arange(24) * ht.HOP_S
    emb = np.array([profile if i < 12 else np.eye(4)[1] for i in range(24)], np.float32)
    turns = ht.turns(starts, emb, profile)
    assert [r for _, _, r in turns] == ["host", "guest"]
    assert turns[0][0] == 0.0 and turns[-1][1] == round(starts[-1] + ht.WINDOW_S, 2)
    assert ht.turns(np.zeros(0), np.zeros((0, 4)), profile) == []


@pytest.mark.skipif(not ROOT.exists(), reason="needs the G: day folders")
def test_the_real_footage_passes_the_check():
    profile = ht.load_profile()
    turns_of = {}
    for lab in LABELS:
        folder = next(ROOT.glob(f"{lab['day']}*"))
        turns_of[_key(lab)] = ht.turns(*ht.windows(folder / "1. FOOTAGE" / lab["file"]), profile)
    lines, fails = ht.check(turns_of, LABELS)
    assert fails == [], lines
