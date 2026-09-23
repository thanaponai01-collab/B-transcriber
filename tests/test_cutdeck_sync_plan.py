"""cutdeck.sync_plan — one test per multi-cam shooting scenario (plan agreed 2026-09-23).

Synthetic, known answers: one "event" is recorded by several clips, each with its own mic noise
and level, cut at known times. Every synced clip must land within 1 ms of where it truly
belongs (a 25 fps frame is 40 ms); everything else must be reported with the right reason.
"""

from pathlib import Path

import numpy as np
import pytest

from cutdeck.sync_plan import COARSE_RATE, FINE_RATE, SESSION_GAP_S, ClipInput, plan_sync

SR = FINE_RATE
TOL_S = 0.001


def event(duration_s: float, seed: int) -> np.ndarray:
    """Speech-like: noise bursts 0.1-0.4 s long separated by 0.05-0.3 s pauses. Never repeats."""
    rng = np.random.default_rng(seed)
    out = np.zeros(int(duration_s * SR), dtype=np.float32)
    t = 0
    while t < len(out):
        n = int(rng.uniform(0.1, 0.4) * SR)
        burst = rng.standard_normal(n).astype(np.float32) * rng.uniform(0.2, 1.0)
        out[t:t + n] = burst[: len(out) - t]
        t += n + int(rng.uniform(0.05, 0.3) * SR)
    return out


class Shoot:
    """Clips cut from events at known times; the loader serves them like ffmpeg would."""

    def __init__(self):
        self.audio: dict[str, np.ndarray] = {}
        self.truth: dict[str, tuple[str, float]] = {}  # clip -> (event name, start in event)
        self.clips: list[ClipInput] = []
        self.loads: list[tuple[str, int]] = []

    def clip(self, cid, source, event_name, t0, t1, *, noise=0.05, gain=1.0, speed=1.0, seed=0):
        rng = np.random.default_rng(1000 + len(self.clips) + seed)
        if speed == 1.0:
            a = source[int(t0 * SR):int(t1 * SR)].copy()
        else:  # a recorder whose clock runs slightly fast or slow
            n = int((t1 - t0) * SR)
            a = np.interp(t0 * SR + np.arange(n) * speed, np.arange(len(source)), source).astype(np.float32)
        a = gain * a + noise * rng.standard_normal(len(a)).astype(np.float32)
        self.add(cid, a, event_name, t0)

    def add(self, cid, audio, event_name=None, t0=0.0):
        self.audio[cid] = audio
        if event_name is not None:
            self.truth[cid] = (event_name, t0)
        self.clips.append(ClipInput(cid, Path(f"{cid}.mp4"), len(audio) / SR if audio is not None and len(audio) else 5.0))

    def loader(self, path, rate, start_s=None, duration_s=None):
        cid = Path(path).stem
        self.loads.append((cid, rate))
        a = self.audio[cid]
        if a is None:
            raise RuntimeError("Stream map '0:a' matches no streams")
        if start_s is not None:
            a = a[int(round(start_s * SR)):]
        if duration_s is not None:
            a = a[:int(round(duration_s * SR))]
        if rate == SR:
            return a
        step = SR // rate
        n = len(a) // step
        return a[: n * step].reshape(n, step).mean(axis=1)

    def plan(self):
        return plan_sync(self.clips, self.loader)


def by_id(plan):
    return {p.clip_id: p for p in plan.placements}


def assert_session_true(plan, shoot, ids):
    """Every clip in `ids` is placed, in one session, at its true position relative to the others."""
    got = by_id(plan)
    for cid in ids:
        assert got[cid].status in ("anchor", "synced"), (cid, got[cid])
    sessions = {got[c].session for c in ids}
    assert len(sessions) == 1, sessions
    first = min(ids, key=lambda c: shoot.truth[c][1])
    for cid in ids:
        want = shoot.truth[cid][1] - shoot.truth[first][1]
        have = got[cid].start_s - got[first].start_s
        assert abs(have - want) < TOL_S, (cid, have, want)


# 1. Every camera rolls together, each with its own audio.
def test_all_cameras_roll_together():
    s, ev = Shoot(), event(60, seed=1)
    s.clip("cam1", ev, "ev", 0, 60)
    s.clip("cam2", ev, "ev", 0, 60, gain=0.4)
    s.clip("cam3", ev, "ev", 0, 60, noise=0.2)
    plan = s.plan()
    assert_session_true(plan, s, ["cam1", "cam2", "cam3"])
    assert plan.sessions == 1 and plan.unplaced == []


# 2. Cameras start part-way through; the recorder runs the whole time. The user drags the
#    recorder in last, so input order must not matter.
def test_cameras_start_part_way_through():
    s, ev = Shoot(), event(120, seed=2)
    s.clip("cam1", ev, "ev", 10.37, 60)
    s.clip("cam2", ev, "ev", 50.5, 110)
    s.clip("rec", ev, "ev", 0, 120, noise=0.01)
    plan = s.plan()
    assert_session_true(plan, s, ["cam1", "cam2", "rec"])
    assert by_id(plan)["rec"].start_s == pytest.approx(0.0)


# 3. The recorder split into two files that do not overlap each other; a camera spans the split.
#    The old XML Sync took only the first file as the reference and lost the rest.
def test_recorder_split_into_files():
    s, ev = Shoot(), event(120, seed=3)
    s.clip("rec1", ev, "ev", 0, 60)
    s.clip("rec2", ev, "ev", 60, 120)
    s.clip("cam1", ev, "ev", 40, 100)
    s.clip("cam2", ev, "ev", 90, 115)
    plan = s.plan()
    assert_session_true(plan, s, ["rec1", "rec2", "cam1", "cam2"])


# 4. No single recording covers everything: each clip only overlaps its neighbour.
def test_chain_with_no_covering_clip():
    s, ev = Shoot(), event(100, seed=4)
    s.clip("a", ev, "ev", 0, 40)
    s.clip("b", ev, "ev", 30, 70)
    s.clip("c", ev, "ev", 60, 100)
    s.clip("d", ev, "ev", 5, 38)  # shorter than every link, overlaps only a
    plan = s.plan()
    assert_session_true(plan, s, ["a", "b", "c", "d"])


# 5. Two separate sessions (morning / afternoon) that never overlap. Each syncs on its own and
#    they are laid out in timeline order with a gap, not dumped as failures.
def test_separate_sessions_in_timeline_order():
    s = Shoot()
    morning, afternoon = event(60, seed=5), event(50, seed=6)
    s.clip("am_cam", morning, "am", 5, 55)
    s.clip("am_rec", morning, "am", 0, 60)
    s.clip("pm_cam", afternoon, "pm", 3, 50)
    s.clip("pm_rec", afternoon, "pm", 0, 50)
    plan = s.plan()
    got = by_id(plan)
    assert plan.sessions == 2 and plan.unplaced == []
    assert_session_true(plan, s, ["am_cam", "am_rec"])
    assert_session_true(plan, s, ["pm_cam", "pm_rec"])
    assert got["am_rec"].session == 0 and got["pm_rec"].session == 1
    assert got["pm_rec"].start_s == pytest.approx(60 + SESSION_GAP_S, abs=TOL_S)


# 6. Clips that cannot be synced go to the back with their reason; the rest still sync.
def test_no_audio_silent_and_unrelated_clips_go_to_the_back():
    s, ev, other = Shoot(), event(60, seed=7), event(20, seed=8)
    s.clip("cam", ev, "ev", 10, 50)
    s.clip("rec", ev, "ev", 0, 60)
    s.add("drone", None)
    s.add("muted", np.zeros(10 * SR, dtype=np.float32))
    s.clip("wrong_day", other, "other", 0, 20)
    plan = s.plan()
    got = by_id(plan)
    assert_session_true(plan, s, ["cam", "rec"])
    assert got["drone"].status == "no_audio" and "matches no streams" in got["drone"].reason
    assert got["muted"].status == "silent"
    assert got["wrong_day"].status == "unmatched"
    back = [got["drone"], got["muted"], got["wrong_day"]]
    assert all(p.start_s >= 60 for p in back), "unplaced clips sit after the synced ones"
    starts = [p.start_s for p in back]
    assert starts == sorted(starts), "and keep the user's timeline order"


# 7. Repeated sound: a clip that only contains a section heard twice matches two places equally
#    well. It must be reported, not placed at a guess.
def test_repeated_sound_is_not_placed_at_a_guess():
    s, ev = Shoot(), event(120, seed=9)
    ev[70 * SR:80 * SR] = ev[20 * SR:30 * SR]  # the same 10 s plays twice (a music loop)
    s.clip("rec", ev, "ev", 0, 120)
    s.clip("cam", ev, "ev", 40, 100)
    s.clip("loop_only", ev, "ev", 21, 29)
    got = by_id(s.plan())
    assert got["loop_only"].status == "unmatched"
    assert got["cam"].status == "synced"


# 8. Two recorders drift apart over a long take: placed from the start, flagged for the end.
def test_drift_is_flagged():
    s, ev = Shoot(), event(150, seed=10)
    s.clip("rec", ev, "ev", 0, 150)
    s.clip("cam", ev, "ev", 20, 140, speed=1.0005)  # 500 ppm, deliberately extreme: 60 ms by the end
    got = by_id(s.plan())
    assert got["cam"].status == "synced"
    # The fine match averages over its 20 s window, and the clock moves 10 ms inside it at this
    # rate (1 ms at a realistic 50 ppm). A quarter of a 25 fps frame is the bar here.
    assert got["cam"].start_s - got["rec"].start_s == pytest.approx(20, abs=0.010)
    assert got["cam"].drift_ms is not None and abs(got["cam"].drift_ms) > 30
    assert "drifts" in got["cam"].reason


def test_no_drift_warning_when_clocks_agree():
    s, ev = Shoot(), event(150, seed=11)
    s.clip("rec", ev, "ev", 0, 150)
    s.clip("cam", ev, "ev", 20, 140)
    got = by_id(s.plan())
    assert got["cam"].drift_ms is not None and abs(got["cam"].drift_ms) < 1
    assert got["cam"].reason == ""


def test_audio_is_read_whole_only_at_the_coarse_rate():
    """Memory bound: full files load at COARSE_RATE; FINE_RATE reads are short windows."""
    s, ev = Shoot(), event(120, seed=12)
    s.clip("rec", ev, "ev", 0, 120)
    s.clip("cam", ev, "ev", 30, 90)
    calls = []
    real = s.loader
    s.loader = lambda p, r, st=None, d=None: calls.append((r, st, d)) or real(p, r, st, d)
    s.plan()
    assert all(st is None and d is None for r, st, d in calls if r == COARSE_RATE)
    fine = [d for r, st, d in calls if r == FINE_RATE]
    assert fine and max(fine) <= 21
