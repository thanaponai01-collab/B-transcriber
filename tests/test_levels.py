import importlib.util
from pathlib import Path

import numpy as np

from transcribe.audio import levels as lv


def _envelope():
    # floor -60 dB; a word at -30 (100 ms), room tone at -52 (> floor + 6, < floor + 10),
    # a soft tail at -48 (> floor + 10, no seed), digital silence that must not set the floor
    lev = np.full(200, -60.0, dtype=np.float32)
    lev[20:30] = -30.0
    lev[30:33] = -48.0      # the word's tail: grows from the word's seed
    lev[60:70] = -52.0      # room tone
    lev[100:105] = -48.0    # an isolated soft blip: above the grow line, no seed
    lev[150:200] = -150.0   # digital silence
    return lev


def test_floor_ignores_digital_silence():
    assert lv.floor(_envelope()) == -60.0


def test_point_rule_keeps_tails_and_drops_unseeded_blips():
    snd = lv.sound(_envelope(), lv.POINT)
    assert snd[20:33].all()             # word plus its tail
    assert not snd[60:70].any()         # room tone is quiet
    assert not snd[100:105].any()       # above floor + 10 but no seed: quiet
    over = lv.over(_envelope(), lv.POINT)
    assert (over[snd] >= 0).all() and (over[~snd] < 0).all()


def test_min_seed_needs_enough_seed_windows():
    lev = np.full(100, -60.0, dtype=np.float32)
    lev[40:42] = -30.0  # a 20 ms click: two seed windows
    assert not lv.sound(lev, lv.Rule(18, 10, 3)).any()
    assert lv.sound(lev, lv.Rule(18, 10, 2))[40:42].all()


def test_a_gain_changes_no_decision():
    lev = _envelope()
    gained = np.where(lev > lv.DIGITAL_DB, lev + 13.0, lev)
    for rule in (lv.POINT, lv.PAUSE, lv.WORD_EDGE):
        assert (lv.sound(lev, rule) == lv.sound(gained, rule)).all()


def test_quiet_runs():
    assert lv.quiet_runs(_envelope(), 300, lv.POINT) == [(0.33, 2.0)]
    assert lv.quiet_runs(_envelope(), 200, lv.POINT) == [(0.0, 0.2), (0.33, 2.0)]


def test_sweep_scores_planted_points():
    spec = importlib.util.spec_from_file_location("sweep", Path(__file__).parent.parent / "tools" / "sweep_level_rule.py")
    sweep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sweep)
    lev = _envelope()
    # edges at 0.19 s (quiet 10 ms before the word) and 0.25 s (mid-word); mid-words at 0.25 s and 0.65 s (room tone)
    c = sweep.counts(lev, [0.19, 0.25], [0.25, 0.65], lv.POINT, 40)
    assert c[:4] == (1, 2, 1, 2)
    assert sweep.j_score(c) == 0.0
