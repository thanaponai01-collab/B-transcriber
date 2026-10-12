"""Coverage guard — find speech that produced no cue, and offer it a second decode.

Internal to `transcribe/pipeline/`. Pure functions of spans and cues, plus one
injected `redecode` callable, so it is testable without a GPU. It never invents
text: a gap is filled only with tokens an engine decoded from that audio, and a
gap that stays empty is reported, not papered over.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)

MIN_GAP_MS = 600       # speech this long with no cue is a gap
ORPHAN_MS = 300        # an isolated cue shorter than this beside a gap is an orphan
CONTEXT_MS = 1000      # audio decoded on each side of a gap


@dataclass(frozen=True)
class Gap:
    start_ms: int
    end_ms: int

    def to_dict(self) -> dict:
        return {"start_ms": self.start_ms, "end_ms": self.end_ms}


def find_gaps(speech_spans, cues, *, min_gap_ms: int = MIN_GAP_MS) -> list[Gap]:
    """Speech stretches (`(start_ms, end_ms)` pairs) at least `min_gap_ms` long that
    no cue overlaps. A span partly covered contributes its uncovered remainders."""
    covered = sorted((c["start_ms"], c["end_ms"]) for c in cues)
    gaps: list[Gap] = []
    for s, e in sorted(speech_spans):
        cursor = s
        for cs, ce in covered:
            if ce <= cursor:
                continue
            if cs >= e:
                break
            if cs - cursor >= min_gap_ms:
                gaps.append(Gap(cursor, cs))
            cursor = max(cursor, ce)
        if e - cursor >= min_gap_ms:
            gaps.append(Gap(cursor, e))
    return gaps


def find_orphans(cues, gaps, *, orphan_ms: int = ORPHAN_MS, near_ms: int = 250) -> list[int]:
    """Indices of cues shorter than `orphan_ms` that touch a gap (within `near_ms`)."""
    out = []
    for i, c in enumerate(cues):
        if c["end_ms"] - c["start_ms"] >= orphan_ms:
            continue
        if any(c["start_ms"] <= g.end_ms + near_ms and c["end_ms"] >= g.start_ms - near_ms
               for g in gaps):
            out.append(i)
    return out


def fill_gaps(cues, gaps, redecode: Callable[[int, int], list[dict]],
              *, context_ms: int = CONTEXT_MS) -> tuple[list[dict], list[Gap]]:
    """Re-decode each gap with `context_ms` of audio either side. `redecode(lo, hi)`
    returns cue dicts in absolute ms. Only tokens that start inside the gap are kept,
    so context text already present in `cues` is never duplicated.

    Returns `(cues_with_fills_sorted, gaps_still_empty)`."""
    filled = list(cues)
    still_empty: list[Gap] = []
    for g in gaps:
        got = [t for t in redecode(max(0, g.start_ms - context_ms), g.end_ms + context_ms)
               if t["text"].strip() and g.start_ms <= t["start_ms"] < g.end_ms]
        if got:
            logger.info("Coverage guard: refilled %d ms-%d ms with %d cue(s)",
                        g.start_ms, g.end_ms, len(got))
            filled.extend(got)
        else:
            still_empty.append(g)
    filled.sort(key=lambda c: (c["start_ms"], c["end_ms"]))
    return filled, still_empty
