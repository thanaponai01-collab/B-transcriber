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

**5.1 Clock blur** (``blur_spans``): the user's answer (2026-11-23) is "follow the clock exactly".
Blur spans are the timeline seconds whose picture is footage at the main framing with the clock
on in its source second (``episode.json`` ``clock``), padded 0.5 s each side (1 fps samples) and
joined across gaps under 1 s. The box is the template's ``BLUR TIME YT`` (its effect mask: route 1
of HKS spike 1b). ``--check``: no clock second of the YT body left outside a span. Not covered: a
``CutDeck_Hold_*`` still that shows a clock.

**5.5 Ending** (``ending``), timed from L, the end of the last kept footage (the goodbye). The
footage carries on from where the goodbye stops, slowed to about a quarter for 2.84 s, under the
stack of ``Plattern_YT SIZE`` [23.48, 26.32): LAYER_OPACITY 50, LAYER_BLACK TONE+VIGNETTE,
LAYER_ZOOM, plus FILM_DAMAGE2. A red-blue glitch runs L-0.08 to L+0.40, an invert flash L-0.04 to
L+0.08, and the sting ``SFX_โหนกระแส 1.wav`` L to L+3.08. Then ``CG_END LOGO`` at 194 % for 5 s,
L+2.84 to the show end at L+7.84. The adjustment layers' Transform, Lumetri and Invert settings
are not readable from a saved project, and the glitch and film damage carry a blend mode, so those
pieces are pasted from the template (PREMIERE_FACTS "Edit > Copy in one sequence, Edit > Paste in
another"), never rebuilt. The slow-down uses the Speed/Duration dialog (``premiere_set_speed``).
Measured: L+2.84 / L+7.84 on 8 of 11; 20261002 and 20261109 (holdout) run the slow part to the
sting's end, 3.08 s; 20261110 has no slowed footage and its logo starts at L+2.72.

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


SLOW = 2.84       # s of slowed footage after the goodbye, under the template stack
SLOW_SOURCE = 0.68  # s of source it shows (median of the saved endings: 0.31-1.24)
LOGO = 5.0
STING = 3.08
TEMPLATE = ("Plattern_YT SIZE", 23.48, 26.32)  # the stack to paste: sequence, start, end


@dataclass(frozen=True)
class Part:
    role: str
    tl_start: float
    tl_end: float
    media: str | None = None  # a file name, when the part is placed from media
    source_in: float | None = None
    speed: float | None = None  # percent, set after placing


def ending(last_end: float, last_source_out: float) -> list[Part]:
    """The ending after a goodbye that ends at ``last_end`` (timeline) and ``last_source_out``."""
    L = last_end
    return [Part("slow", L, L + SLOW, "footage", last_source_out, round(100 * SLOW_SOURCE / SLOW, 1)),
            Part("stack", L, L + SLOW),
            Part("glitch", L - 2 * FRAME, L + 10 * FRAME, "Glitch redblue.mov"),
            Part("flash", L - FRAME, L + 2 * FRAME),
            Part("sting", L, L + STING, "SFX_โหนกระแส 1.wav", 0.0),
            Part("logo", L + SLOW, L + SLOW + LOGO, "CG_END LOGO โหนกระแส.mp4", 0.0)]


def saved_ending(gold, seq: dict) -> dict[str, tuple[float, float]]:
    """The same roles read from a saved output, timeline (start, end) each."""
    import ntpath
    L = max(k.tl_end for k in gold.keeps if k.tl_end <= gold.show_end + HALF)
    clips = [(kind, c) for kind in ("video", "audio") for t in seq[f"{kind}_tracks"] for c in t["clips"]
             if not c["disabled"] and L - 1 < c["start"] < gold.show_end]

    def span(match) -> tuple[float, float] | None:
        found = [c for kind, c in clips if match(kind, ntpath.basename(c.get("media_path") or "").lower(), c["name"] or "")]
        return (min(c["start"] for c in found), max(c["end"] for c in found)) if found else None

    return {k: v for k, v in {
        "slow": span(lambda kind, m, n: kind == "video" and m in gold_footage(gold)),
        "stack": span(lambda kind, m, n: n.startswith("LAYER_")),
        "glitch": span(lambda kind, m, n: m == "glitch redblue.mov"),
        "flash": span(lambda kind, m, n: n == "Adjustment Layer" and kind == "video"),
        "sting": span(lambda kind, m, n: m == "sfx_โหนกระแส 1.wav"),
        "logo": span(lambda kind, m, n: m == "cg_end logo โหนกระแส.mp4"),
    }.items() if v is not None}


def gold_footage(gold) -> set[str]:
    return {k.media.lower() for k in gold.keeps}


HALF = FRAME / 2
ENDING_TOL = 0.25  # s: every ending part within this of the saved one (descriptive: set after reading all 11)


BLUR_PAD = 0.5   # s each side: the clock is sampled once a second, so a span edge is known to ±0.5 s
BLUR_JOIN = 1.0  # s: blur spans closer than this become one (no flicker between them)


def blur_spans(ls, clocks: dict[str, list], start: float, end: float) -> list[tuple[float, float]]:
    """5.1, the user's rule "follow the clock": timeline spans in [start, end) where the picture is
    footage at the main framing whose source second has the clock on (``clocks``: lower-case media
    name -> episode ``clock`` spans). A zoomed insert pushes the clock out of frame, so it is not
    blurred; a frame hold is read like footage at its held second. ``ls`` are ``hks_audit.layers``."""
    from cutdeck.hks_audit import main_framing, picture_at, wider
    from cutdeck.hks_episode import inside
    main = main_framing(ls, start, end)
    on = []
    t = start + 0.5
    while t < end:
        pic = picture_at(ls, t)
        if (pic is not None and pic.kind == "footage" and not (main and wider(pic.framing, main))
                and inside(clocks.get(pic.media.lower(), []), round(pic.source_at(t)))):
            on.append(t)
        t += 1.0
    spans: list[list[float]] = []
    for t in on:
        a, b = max(start, t - 0.5 - BLUR_PAD), min(end, t + 0.5 + BLUR_PAD)
        if spans and a - spans[-1][1] < BLUR_JOIN:
            spans[-1][1] = b
        else:
            spans.append([a, b])
    return [(round(a / FRAME) * FRAME, round(b / FRAME) * FRAME) for a, b in spans]


def check_blur(folder: Path) -> dict:
    """Every clock second the YT body shows at the main framing falls inside a planned span, and the
    planned spans add no blur where the gold had neither a clock nor a blur."""
    from cutdeck.hks_audit import blur_samples, layers
    from cutdeck.hks_build import _sequence
    from cutdeck.hks_episode import inside, load
    from cutdeck.hks_gold import read_day
    from cutdeck.prproj_reader import read_project
    gold = read_day(folder)
    seq = _sequence(read_project(gold.project), gold.yt.sequence)
    ep = load(folder.name[:8])
    clocks = {n.lower(): f.get("clock", []) for n, f in ep["files"].items()}
    ls = layers(seq, set(clocks))
    start = gold.yt.hook_end or 0.0
    spans = blur_spans(ls, clocks, start, gold.yt.show_end)

    def clock_of(layer, t):
        return None if layer.kind != "footage" else inside(clocks[layer.media.lower()], round(layer.source_at(t)))

    rows = blur_samples(ls, clock_of, start, gold.yt.show_end)
    covered = lambda t: any(a <= t < b for a, b in spans)
    missed = [r["t"] for r in rows if r["state"] == "clock" and not covered(r["t"])]
    planned = sum(b - a for a, b in spans)
    gold_blur = sum(r["blurred"] for r in rows)
    return {"day": folder.name[:8], "spans": len(spans), "planned_s": round(planned, 1),
            "gold_blur_s": gold_blur, "clock_s": sum(r["state"] == "clock" for r in rows),
            "missed": len(missed), "pass": not missed}


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
    last = max((k for k in gold.yt.keeps if k.tl_end <= gold.yt.show_end + HALF), key=lambda k: k.tl_end)
    planned = {p.role: (p.tl_start, p.tl_end) for p in ending(last.tl_end, last.source_out)}
    saved = saved_ending(gold.yt, seq)
    off = {role: round(max(abs(a - planned[role][0]), abs(b - planned[role][1])), 2)
           for role, (a, b) in saved.items() if max(abs(a - planned[role][0]), abs(b - planned[role][1])) > HALF}
    return {"day": folder.name[:8], "pieces": len(got), "saved": len(want), "agree": round(share, 4),
            "covered": covered, "ending_off": off, "ending_missing": sorted(set(planned) - set(saved)),
            "pass": covered and share >= MIN_AGREE}


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
            r, b = check_day(folder), check_blur(folder)
            r["ending_ok"] = not r["ending_off"] or max(r["ending_off"].values()) <= ENDING_TOL
            print(group, r)
            print(group, b)
            ok &= r["pass"] and r["ending_ok"] and not r["ending_missing"] and b["pass"]
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
