"""Break and fixed-graphics finder (cutdeck/hks_breaks.py, plan step 2.2): the pure parts on
synthetic data, then the 20261120 drops on the real footage when the G: drive and the reference
clips (test_projects/hks_refs, cut by --cut-refs) are there."""

from pathlib import Path

import numpy as np
import pytest

from cutdeck import hks_breaks as hb

RNG = np.random.default_rng(7)
DAY = Path(r"G:\Me\Works\20261120 - โหนกระแส")


def noise(frames: int) -> np.ndarray:
    return RNG.normal(0, 1, (frames, hb.N_MELS)).astype(np.float32)


def test_a_clip_matches_where_it_was_put_despite_gain_and_tilt():
    ref, mel = noise(200), noise(3000)
    tilt = np.linspace(-1, 1, hb.N_MELS, dtype=np.float32)
    mel[1200:1400] = ref + 2.0 + tilt  # louder and with another spectral tilt: still the same sound
    curve = hb.match_curve(ref, mel)
    assert int(curve.argmax()) == 1200 and curve[1200] > 0.99
    assert np.delete(curve, range(1150, 1250)).max() < 0.3
    assert hb.peaks(curve, hb.MATCH, 200) == [1200]


def test_locate_matches_the_core_and_may_start_before_the_file():
    ref = noise(600)
    mel = noise(2000)
    mel[:500] = ref[100:]  # the file starts 100 frames into the clip
    mel[1200:1800] = ref
    mel[1200:1240] = noise(40)  # a voice over the clip's first frames does not stop the match
    assert [i for i, _ in hb.locate(ref, mel)] == [-100, 1200]


def test_heard_ends_where_the_file_stops_sounding_like_the_clip():
    ref, mel = noise(400), noise(2000)
    mel[1000:1400] = ref
    mel[1300:1400] = noise(100)  # the host talks over the last 4 s of the music
    a, b = hb.heard(ref, mel, 1000)
    assert abs(a - 1000) <= hb.AGREE_WIN // 2 and abs(b - 1300) <= hb.AGREE_WIN // 2


def test_shared_span_is_what_most_partners_share():
    base = noise(1000)
    partners = []
    for lag, (lo, hi) in ((100, (300, 700)), (-200, (320, 690)), (0, (500, 600))):
        p = noise(1400)
        p[lo + lag:hi + lag] = base[lo:hi]
        partners.append((p, lag))
    a, b = hb.shared_span(base, 550, partners)
    assert abs(a - 320) <= hb.AGREE_WIN // 2 and abs(b - 690) <= hb.AGREE_WIN // 2


def test_combine_gives_ordered_drops_that_never_overlap():
    drops = hb.combine([
        {"start": 99.5, "end": 160.0, "kind": "clock_off", "why": ""},
        {"start": 0.0, "end": 22.4, "kind": "opening", "why": ""},
        {"start": 10.0, "end": 17.0, "kind": "bumper", "why": "sting inside the opening"},
        {"start": 21.9, "end": 29.0, "kind": "bumper", "why": "sting leaving the opening"},
        {"start": 100.0, "end": 107.0, "kind": "bumper", "why": ""},
        {"start": 150.0, "end": 159.6, "kind": "bumper", "why": ""},
    ])
    assert [(d["start"], d["end"], d["kind"]) for d in drops] == [
        (0.0, 22.4, "opening"), (22.4, 29.0, "bumper"),
        (99.5, 100.0, "clock_off"),  # rule 7 drops the whole clock-off run, however short the rest
        (100.0, 107.0, "bumper"), (107.0, 150.0, "clock_off"), (150.0, 159.6, "bumper"),
        (159.6, 160.0, "clock_off")]
    assert hb.combine([{"start": 0.0, "end": 22.4, "kind": "opening", "why": ""},
                       {"start": 21.9, "end": 23.0, "kind": "bumper", "why": ""}])[1:] == []


def test_clock_edges_go_to_a_hard_cut_in_their_second_else_its_middle():
    diffs = [(819.2, 3.0), (819.48, 40.0), (819.8, 60.0), (820.4, 90.0)]
    assert hb.edge_in_second(diffs, 820) == 819.8
    assert hb.edge_in_second([(819.48, 10.0)], 820) == 819.5
    assert hb.last_cut_before([(4425.0, 50.0), (4428.36, 73.5), (4433.3, 5.0)], 4433.4) == 4428.36
    assert hb.last_cut_before([(4420.0, 50.0)], 4433.4) is None


def test_the_20261120_check_gates_each_boundary_but_the_sponsor_start():
    drops = [{"start": 0.0, "end": 22.36, "kind": "opening"},
             {"start": 817.84, "end": 875.6, "kind": "bumper"},
             {"start": 2005.12, "end": 2069.64, "kind": "bumper"},
             {"start": 4428.38, "end": 4447.96, "kind": "credits"}]
    lines = hb.check_1120(drops, 4447.96)
    assert [l.split()[0] for l in lines] == ["ok", "ok", "info", "FAIL", "ok", "ok", "ok", "ok"]
    assert hb.check_1120(drops[:3], 4447.96)[-1].startswith("FAIL 20261120 credits")


def test_kept_drops_fail_unless_they_are_the_kept_flood_maps():
    keeps = [(300.0, 320.0), (900.0, 900.5)]
    drops = [{"start": 256.5, "end": 557.5, "kind": "clock_off"},
             {"start": 890.0, "end": 905.0, "kind": "bumper"}]
    assert hb.check_kept("20261001", drops, keeps) == ([], ["20261001 clock_off 256.50-557.50: 20.00 s kept in YT"])
    fails, _ = hb.check_kept("20261003", drops, keeps)
    assert fails == ["20261003 clock_off 256.50-557.50: 20.00 s kept in YT"]


def test_a_dip_is_covered_without_its_first_and_last_second():
    covered = [{"start": 819.6, "end": 875.4, "kind": "clock_off"}]
    assert hb.check_dips("20261120", covered + [{"start": 2006.9, "end": 2068.1, "kind": "bumper"}]) == []
    assert hb.check_dips("20261120", covered + [{"start": 2007.5, "end": 2068.1, "kind": "bumper"}]) == [
        "20261120 dip 2006-2069 not covered (0.50 s open)"]


@pytest.mark.skipif(not DAY.exists() or not (hb.REFS_DIR / "refs.json").exists(),
                    reason="needs the G: day folders and the reference clips")
def test_20261120_drops_hold_the_gold_boundaries_the_signals_can_place():
    path = DAY / "1. FOOTAGE" / "HKS Facebook 201169 Full.mp4"
    drops = hb.file_drops(path, hb.load_refs())
    lines = hb.check_1120(drops, round(len(hb.audio_features(str(path))[0]) / hb.FPS, 2))
    # break 1 end is left out: the user dropped the host's welcome-back line there only
    assert all(l.startswith("ok") for l in lines if not l.startswith("info") and "break 1 end" not in l)
    assert hb.check_dips("20261120", drops) == []
