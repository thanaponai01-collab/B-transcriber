"""HKS build plan Phase 5: finishing a cut long form, as build items for ``build_sequence``.

Every step takes a finished long form (the user's hand cut first, a draft later) and returns what
to add. Rules measured on the 11 saved ``1 YOUTUBE`` sequences (2026-11-23):

**5.2 Music bed** (``music_bed``). ``[BGM]Where Everything Began.wav`` (59.28 s) is laid in two
alternating lanes, one piece every 56.48 s from 0, so neighbours overlap 2.8 s. It plays at
-24 dB under the hook (to two frames after the hook SFX starts), then -33 dB. The last piece is
placed so its own end lands on the show end, at the first slot at or after
``show end - 59.28``, and plays its last 7.84 s at -12 dB (the sting and the end logo). It
replaces that slot's regular piece. On all 11 episodes the period is exactly 56.48 s and the hook
level -24 dB (20261020: -27). Three episodes end at -9 dB instead of -12, and four start the last
piece off the slot grid (20261001, 20261003, 20261012, 20261112). ``--check`` scores the bed
against the saved one frame by frame.

    python -m cutdeck.hks_finish --all G:\\Me\\Works --check [--holdout]
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

FRAME = 0.04
BGM = "[bgm]where everything began.wav"
PIECE = 59.28    # s, the file's length
PERIOD = 56.48   # s between piece starts
HOOK_TAIL = 2 * FRAME  # the hook level runs this far past the hook SFX start
END_LOUD = 7.84  # s at the end level: the sting and the end logo
HOOK_DB, BODY_DB, END_DB = -24.0, -33.0, -12.0
MIN_AGREE = 0.95  # share of frames where the bed plays the same music second at the same level; set before the first run


@dataclass(frozen=True)
class Piece:
    tl_start: float
    tl_end: float
    source_in: float
    lane: int  # 0 or 1: two tracks, so overlapping pieces never sit on one track
    db: float


def level(db: float) -> float:
    """Linear Volume Level for ``db`` (PREMIERE_FACTS, HKS spike 1c: dB = 20 log10(v) + 15)."""
    return 10 ** ((db - 15) / 20)


def db_of(linear: float) -> float:
    return 20 * math.log10(linear) + 15


def _split(p: Piece, at: float, db: float) -> list[Piece]:
    """``p`` up to ``at``, then the rest at ``db``."""
    if not p.tl_start < at < p.tl_end:
        return [p]
    return [Piece(p.tl_start, at, p.source_in, p.lane, p.db),
            Piece(at, p.tl_end, p.source_in + at - p.tl_start, p.lane, db)]


def music_bed(hook_end: float | None, show_end: float) -> list[Piece]:
    """The bed for a show of ``show_end`` s whose hook ends at ``hook_end`` (None: no hook)."""
    if show_end <= PIECE:
        start = 0.0
    else:
        start = math.ceil((show_end - PIECE) / PERIOD - 1e-9) * PERIOD  # first slot at or after show end - piece
    pieces = [Piece(k * PERIOD, k * PERIOD + PIECE, 0.0, k % 2, BODY_DB)
              for k in range(round(start / PERIOD))]
    last_in = start - (show_end - PIECE)
    pieces.append(Piece(start, show_end, last_in, round(start / PERIOD) % 2, BODY_DB))
    out = []
    for p in pieces:
        parts = [p]
        if hook_end is not None:
            parts = [q for part in parts for q in _split(part, hook_end + HOOK_TAIL, BODY_DB)]
            parts = [Piece(q.tl_start, q.tl_end, q.source_in, q.lane, HOOK_DB if q.tl_end <= hook_end + HOOK_TAIL + 1e-9 else q.db)
                     for q in parts]
        if p is pieces[-1]:
            parts = [q for part in parts for q in _split(part, show_end - END_LOUD, END_DB)]
        out += parts
    return out


def playing(pieces: list[Piece], t: float) -> set[tuple[float, float]]:
    """(music second, dB) of every piece sounding at ``t``, to the frame."""
    return {(math.floor((p.source_in + t - p.tl_start) / FRAME + 1e-6), round(p.db)) for p in pieces if p.tl_start <= t < p.tl_end}


def agreement(a: list[Piece], b: list[Piece], end: float) -> float:
    n = max(1, round(end / FRAME))
    same = sum(playing(a, (i + 0.5) * FRAME) == playing(b, (i + 0.5) * FRAME) for i in range(n))
    return same / n


def saved_bed(seq: dict, show_end: float) -> list[Piece]:
    """The BGM pieces of a saved sequence, lanes numbered from its lowest BGM track."""
    import ntpath
    found = []
    for track in seq["audio_tracks"]:
        for c in track["clips"]:
            if ntpath.basename(c.get("media_path") or "").lower() == BGM and c["start"] < show_end and not c["disabled"]:
                lv = next((e["params"]["Level"]["value"] for e in c["effects"] if "Level" in (e.get("params") or {})), None)
                found.append((track["index"], c, lv))
    low = min((i for i, _, _ in found), default=0)
    return [Piece(c["start"], c["end"], c["source_in"], i - low, round(db_of(lv), 1) if lv else BODY_DB)
            for i, c, lv in found]


def items(pieces: list[Piece], media: str, tracks: tuple[int, int]) -> list[dict]:
    """``build_sequence`` items: lane 0 on ``tracks[0]``, lane 1 on ``tracks[1]``."""
    from cutdeck.hks_build import ticks
    return [{"id": f"BGM{k}@{p.tl_start:.2f}", "media": media, "in_ticks": ticks(p.source_in),
             "out_ticks": ticks(p.source_in + p.tl_end - p.tl_start), "at_ticks": ticks(p.tl_start),
             "v": None, "a": tracks[p.lane], "level": level(p.db)} for k, p in enumerate(pieces)]


def check_day(folder: Path) -> dict:
    from cutdeck.hks_build import _sequence
    from cutdeck.hks_gold import read_day
    from cutdeck.prproj_reader import read_project
    gold = read_day(folder)
    seq = _sequence(read_project(gold.project), gold.yt.sequence)
    want = saved_bed(seq, gold.yt.show_end)
    got = music_bed(gold.yt.hook_end, gold.yt.show_end)
    covered = all(playing(got, (i + 0.5) * FRAME) for i in range(round(gold.yt.show_end / FRAME)))
    share = agreement(got, want, gold.yt.show_end)
    return {"day": folder.name[:8], "pieces": len(got), "saved": len(want), "agree": round(share, 4),
            "covered": covered, "pass": covered and share >= MIN_AGREE}


def main(argv: list[str] | None = None) -> None:
    from cutdeck.hks_gold import day_folders
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--all", required=True)
    p.add_argument("--check", action="store_true")
    p.add_argument("--holdout", action="store_true")
    args = p.parse_args(argv)
    tuning, holdout = day_folders(args.all)
    ok = True
    for group, folders in (("tuning", tuning), ("holdout", holdout if args.holdout else [])):
        for folder in folders:
            r = check_day(folder)
            print(group, r)
            ok &= r["pass"]
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
