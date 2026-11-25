"""The shared sound/quiet rule on a 10 ms level envelope (docs/LEVEL_RULES_PLAN.md).

A window is judged against the file's own noise floor, so a linear gain on the file changes no
decision unless the floor clamp binds (see ``FLOOR_CLAMP_DB``). A rule is hysteresis in ``ingest.sound_runs``' form: a run of windows at least
``grow_db`` over the floor is sound when it holds ``min_seed`` windows at least ``seed_db`` over
it. ``grow_db`` sets which windows are quiet; ``seed_db`` stops room tone from flickering into
sound. Each question has its own measured rule.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

ENVELOPE_MS = 10
# The floor is held inside these bounds. On sources with gated silence (20261112, floor -69 to
# -74 dB) the 5th percentile sits under the room tone between words; without the clamp the
# one-frame quiet check scores J 44 instead of 67 there (2026-11-25). It is the one absolute
# piece left: replacing it with a gain-invariant floor needs its own sweep and a fresh holdout.
FLOOR_CLAMP_DB = (-65.0, -35.0)


@dataclass(frozen=True)
class Rule:
    seed_db: float
    grow_db: float
    min_seed: int = 1


# "Is this point quiet?" (timeline edges, word_cut, word edges, hks_cut_check). +10 and +12 won
# the "any quiet window within 40 ms" sweep on the 8 HKS tuning days and on held-out 20261109 /
# 20261118, but lost 5 J on held-out 20261002 (a YouTube master, floor -46 dB), and word_cut asks
# a different question (all windows within 20 ms quiet). +6 stays until a margin wins both ways.
QUIET = Rule(6.0, 6.0)
# "Is this a pause long enough to cut?": hks_tighten --check, 8 tuning days.
PAUSE = Rule(18.0, 18.0)


def floor(levels) -> float:
    """The noise floor: the 5th percentile window level, held inside ``FLOOR_CLAMP_DB``."""
    lo, hi = FLOOR_CLAMP_DB
    return float(np.clip(np.percentile(levels, 5), lo, hi)) if len(levels) else lo


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
