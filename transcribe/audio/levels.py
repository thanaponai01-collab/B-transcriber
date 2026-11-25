"""The shared sound/quiet rule on a 10 ms level envelope (docs/LEVEL_RULES_PLAN.md).

A window is judged against the file's own noise floor, so a linear gain on the file changes no
decision. A rule is hysteresis in ``ingest.sound_runs``' form: a run of windows at least
``grow_db`` over the floor is sound when it holds ``min_seed`` windows at least ``seed_db`` over
it. ``grow_db`` sets which windows are quiet; ``seed_db`` stops room tone from flickering into
sound. Each question has its own measured rule.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

ENVELOPE_MS = 10
DIGITAL_DB = -100.0  # windows at or below this are digital silence, not the room


@dataclass(frozen=True)
class Rule:
    seed_db: float
    grow_db: float
    min_seed: int = 1


# "Is this point quiet?" for cuts snapped within one frame: chosen by tools/sweep_level_rule.py on
# the 8 HKS tuning days, then scored once on held-out 20261109 and 20261118.
POINT = Rule(18.0, 10.0, 3)
# "Is this a pause long enough to cut?": hks_tighten --check, 8 tuning days.
PAUSE = Rule(18.0, 18.0)
# Word edges fitted to the sound (timeline_transcript.tighten). Not swept yet.
WORD_EDGE = Rule(6.0, 6.0)


def floor(levels) -> float:
    """The noise floor: 5th percentile of the windows that are not digital silence."""
    live = np.asarray(levels)[np.asarray(levels) > DIGITAL_DB]
    return float(np.percentile(live, 5)) if len(live) else DIGITAL_DB


def sound(levels, rule: Rule) -> np.ndarray:
    """Per window: is it sound under ``rule``?"""
    lev = np.asarray(levels)
    f = floor(lev)
    grow = lev >= f + rule.grow_db
    edges = np.flatnonzero(np.diff(np.concatenate(([0], grow.astype(np.int8), [0]))))
    starts, ends = edges[::2], edges[1::2]
    seeds = np.concatenate(([0], np.cumsum(lev >= f + rule.seed_db)))
    keep = seeds[ends] - seeds[starts] >= rule.min_seed
    out = np.zeros(len(lev), dtype=bool)
    for a, b in zip(starts[keep], ends[keep]):
        out[a:b] = True
    return out


def over(levels, rule: Rule) -> np.ndarray:
    """dB over ``rule``'s sound line (floor + ``grow_db``) per window; every quiet window is
    negative, including one above the line that the rule leaves quiet (no seed in its run)."""
    lev = np.asarray(levels, dtype=np.float32)
    out = lev - np.float32(floor(lev) + rule.grow_db)
    quiet = ~sound(lev, rule)
    out[quiet] = np.minimum(out[quiet], np.float32(-0.1))
    return out


def quiet_runs(levels, min_ms: int, rule: Rule) -> list[tuple[float, float]]:
    """(start s, end s) of every run of at least ``min_ms`` of quiet windows under ``rule``."""
    quiet = ~sound(levels, rule)
    edges = np.flatnonzero(np.diff(np.concatenate(([0], quiet.astype(np.int8), [0]))))
    return [(int(a) * ENVELOPE_MS / 1000, int(b) * ENVELOPE_MS / 1000)
            for a, b in zip(edges[::2], edges[1::2]) if (b - a) * ENVELOPE_MS >= min_ms]
