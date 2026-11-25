import importlib.util
from pathlib import Path

import numpy as np

from transcribe.audio import levels as lv

HYST = lv.Rule(18.0, 10.0, 3)


def _envelope():
    # floor -60 dB; a word at -30 (100 ms), room tone at -52 (> floor + 6, < floor + 10),
    # a soft tail at -48 (> floor + 10, no seed), then digital silence
    lev = np.full(200, -60.0, dtype=np.float32)
    lev[20:30] = -30.0
    lev[30:33] = -48.0      # the word's tail: grows from the word's seed
    lev[60:70] = -52.0      # room tone
    lev[100:105] = -48.0    # an isolated soft blip: above the grow line, no seed
    lev[180:200] = -150.0   # digital silence: 10 % of the windows, so it sets the 5th percentile
    return lev


def test_floor_is_clamped():
    assert lv.floor(_envelope()) == -65.0                       # digital silence: held at -65
    assert lv.floor(np.full(100, -20.0, dtype=np.float32)) == -35.0
    assert lv.floor(np.full(100, -50.0, dtype=np.float32)) == -50.0


def test_hysteresis_keeps_tails_and_drops_unseeded_blips():
    snd = lv.sound(_envelope(), HYST)
    assert snd[20:33].all()             # word plus its tail
    assert not snd[60:70].any()         # room tone is quiet
    assert not snd[100:105].any()       # above the grow line but no seed: quiet
    over = lv.over(_envelope(), HYST)
    assert (over[snd] >= 0).all() and (over[~snd] < 0).all()


def test_single_margin_rule_is_a_plain_threshold():
    lev = _envelope()
    assert (lv.sound(lev, lv.QUIET) == (lev >= -59.0)).all()  # clamped floor -65 + 6


def test_min_seed_needs_enough_seed_windows():
    lev = np.full(100, -60.0, dtype=np.float32)
    lev[40:42] = -30.0  # a 20 ms click: two seed windows
    assert not lv.sound(lev, lv.Rule(18, 10, 3)).any()
    assert lv.sound(lev, lv.Rule(18, 10, 2))[40:42].all()


def test_a_gain_changes_no_decision_inside_the_clamp():
    lev = np.full(200, -55.0, dtype=np.float32)
    lev[20:30], lev[60:70], lev[100:105] = -25.0, -47.0, -43.0
    gained = lev - 5.0
    for rule in (lv.QUIET, lv.PAUSE, HYST):
        assert (lv.sound(lev, rule) == lv.sound(gained, rule)).all()


def test_quiet_runs():
    assert lv.quiet_runs(_envelope(), 300, HYST) == [(0.33, 2.0)]
    assert lv.quiet_runs(_envelope(), 200, HYST) == [(0.0, 0.2), (0.33, 2.0)]


def test_sweep_scores_planted_points():
    spec = importlib.util.spec_from_file_location("sweep", Path(__file__).parent.parent / "tools" / "sweep_level_rule.py")
    sweep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sweep)
    # edges at 0.19 s (quiet 10 ms before the word) and 0.25 s (mid-word); mid-words at 0.25 s and 0.65 s (room tone)
    c = sweep.counts(_envelope(), [0.19, 0.25], [0.25, 0.65], HYST, 40)
    assert c[:4] == (1, 2, 1, 2)
    assert sweep.j_score(c) == 0.0
    # every window within 20 ms: 0.19 s touches the word, so only the room-tone mid-word is quiet
    assert sweep.counts(_envelope(), [0.19, 0.25], [0.25, 0.65], HYST, 20, "all")[:4] == (0, 2, 1, 2)


def test_quiet_runs_finds_long_quiet_stretches_only():
    lev = np.full(200, -20.0, dtype=np.float32)
    lev[:20] = -60.0      # 200 ms quiet: too short at min 300 ms
    lev[50:90] = -60.0    # 400 ms quiet
    lev[150:190] = -50.0  # 400 ms at floor + 10 dB: quiet only with a wider margin
    assert lv.quiet_runs(lev, 300, lv.Rule(6.0, 6.0)) == [(0.5, 0.9)]
    assert lv.quiet_runs(lev, 300, lv.Rule(12.0, 12.0)) == [(0.5, 0.9), (1.5, 1.9)]
