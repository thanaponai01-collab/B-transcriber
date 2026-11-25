"""HKS build plan 4.1: tighten inside the keeps, only where the cut can be hidden.

A pause inside a keep becomes a cut when the cut can be hidden:
- the picture there is a news clip or full-frame footage (``layout`` ``clip`` / ``footage``,
  plan 2.4): the cut is listed as ``needs_cover`` and 4.3 covers it with B-roll;
- or, in studio picture, a legal cut point (``cut_points``, plan 2.5: a camera change, an inset
  camera change or a still) sits on the pause: the cut is moved onto that point and needs no cover
  (the user's rule, 2026-11-23).
Anywhere else the pause stays (studio picture with no camera change: a jump cut).

Pauses come from the audio, not from word times: Whisper stretches words over pauses (90 % of the
gaps between words on 20261120 are under 0.1 s). ``pauses`` reads them from the shared level
envelope (``timeline_transcript.quiet_runs``). ``silences`` (ffmpeg ``silencedetect``) stays for
``hks_judge`` and ``--quiet ffmpeg``.

``--check`` isolates 4.1 from the content cut: it takes the user's own keeps with every gap under
3 s closed (the story cut, without its tightening), tightens them, and scores the result with
``hks_score`` per cut class (< 0.6 s and 0.6-3 s are the tightening classes). Jump cuts must be 0.

    python -m cutdeck.hks_tighten --all G:\\Me\\Works --check [--holdout]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from cutdeck import hks_cache

CACHE = Path(tempfile.gettempdir()) / "hks_silence"
NOISE_DB = -35
MIN_SILENCE = 0.3   # s that silencedetect reports
MIN_PAUSE = 0.6     # s: a pause shorter than this is pace, not dead air
PAD_POST = 0.15     # s of silence left after the last word
PAD_PRE = 0.10      # s of silence left before the next word
SNAP = 0.5          # s: a legal cut point this close to the pause takes the cut
CLOSE_GAPS = 3.0    # s: --check closes the user's gaps shorter than this to get the untightened cut


def silences(path: str, cache: Path = CACHE) -> list[tuple[float, float]]:
    """Silences of at least MIN_SILENCE s under NOISE_DB in the file's audio, cached."""
    key = cache / f"{re.sub(r'[^A-Za-z0-9]+', '_', Path(path).stem)[:40]}_{Path(path).stat().st_size}.json"
    if key.exists():
        hks_cache.touch(key)
        return [tuple(s) for s in json.loads(key.read_text())]
    err = subprocess.run(["ffmpeg", "-v", "info", "-i", path, "-vn", "-af",
                          f"silencedetect=noise={NOISE_DB}dB:d={MIN_SILENCE}", "-f", "null", "-"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    out = list(zip(starts, ends))
    cache.mkdir(parents=True, exist_ok=True)
    key.write_text(json.dumps(out))
    hks_cache.trim(cache.parent)
    return out


FLOOR_PAUSE_DB = 18.0  # floor + this: the margin that matches silencedetect -35 dB on the 8 tuning days


def pauses(path: str) -> list[tuple[float, float]]:
    """The pauses tightening cuts: runs of the shared level envelope of ``timeline_transcript``
    below its noise floor + FLOOR_PAUSE_DB (docs/SYSTEM_LAYERS.md). At the point-quiet margin
    (+6 dB) it finds too few pauses (0.6-3 s recall 0.31 -> 0.13); at +18 dB it scores the same
    as ffmpeg silencedetect -35 dB, which it replaced (``--check``, 2026-11-25)."""
    from cutdeck.timeline_transcript import media_sha256, quiet_runs, source_levels
    root = Path(__file__).resolve().parent.parent
    levels = source_levels(path, root / "output" / "timeline_transcripts" / "levels"
                           / f"{media_sha256(path, root / 'transcriber.db')}.npy")
    return quiet_runs(levels, int(MIN_SILENCE * 1000), FLOOR_PAUSE_DB)


QUIET = {"ffmpeg": silences, "floor": pauses}


def kind_at(layout: list, t: float) -> str | None:
    return next((k for a, b, k in layout if a <= t < b), None)


def legal_points(cut_points: list) -> list[float]:
    """Times where an uncovered cut is legal. A still is a run [a, b, "still"]: any time inside it."""
    return [p[0] for p in cut_points if len(p) == 2]


def in_still(cut_points: list, a: float, b: float) -> bool:
    return any(len(p) == 3 and p[0] <= a and b <= p[1] for p in cut_points)


def tighten(keeps: list[tuple[float, float]], silence: list[tuple[float, float]], layout: list,
            cut_points: list) -> tuple[list[tuple[float, float]], list[tuple[float, float]], dict]:
    """(keeps after tightening, the new drops that need a cover, counts by outcome)."""
    points = sorted(legal_points(cut_points))
    drops, covers, n = [], [], {"cover": 0, "camera": 0, "still": 0, "left": 0}
    for ka, kb in keeps:
        for sa, sb in silence:
            if sb - sa < MIN_PAUSE or sa < ka or sb > kb:
                continue
            a, b = sa + PAD_POST, sb - PAD_PRE
            near = [p for p in points if sa - SNAP <= p <= sb + SNAP]
            if in_still(cut_points, a, b):
                drops.append((a, b))
                n["still"] += 1
            elif near:
                # The cut lands on the camera change: drop from the pause up to the change, so the
                # next shot starts the new piece.
                p = min(near, key=lambda x: abs(x - (a + b) / 2))
                lo, hi = (a, p) if p > a + 0.04 else (p, b)
                if hi - lo >= 0.04:
                    drops.append((lo, hi))
                    n["camera"] += 1
            elif kind_at(layout, (a + b) / 2) in ("clip", "footage"):
                drops.append((a, b))
                covers.append((a, b))
                n["cover"] += 1
            else:
                n["left"] += 1
    out = []
    for ka, kb in keeps:
        cur = ka
        for a, b in sorted(d for d in drops if ka <= d[0] and d[1] <= kb):
            if a > cur:
                out.append((cur, a))
            cur = max(cur, b)
        if kb > cur:
            out.append((cur, kb))
    return out, covers, n


def untightened(keeps: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The user's keeps with every gap under CLOSE_GAPS closed: the story cut before tightening."""
    out: list[list[float]] = []
    for a, b in sorted(keeps):
        if out and a - out[-1][1] < CLOSE_GAPS:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def check_day(folder: Path, quiet: str = "floor") -> dict:
    from cutdeck import hks_score
    from cutdeck.hks_episode import load
    from cutdeck.hks_gold import read_day
    day = read_day(folder)
    gold = hks_score.gold_of(day)
    ep = load(folder.name[:8])
    keeps, covered, counts = {}, {}, {}
    for media in gold.keeps:
        f = next((v for k, v in ep["files"].items() if k.lower() == media.lower()), {})
        base = untightened([(a / 1000, b / 1000) for a, b in gold.keeps[media]])
        path = str(folder / "1. FOOTAGE" / next(k for k in ep["files"] if k.lower() == media.lower()))
        k, c, n = tighten(base, QUIET[quiet](path),f.get("layout", []), f.get("cut_points", []))
        keeps[media], covered[media] = [list(x) for x in k], [list(x) for x in c]
        counts = {x: counts.get(x, 0) + n[x] for x in n}
    proposal = hks_score.parse_proposal({"keeps": keeps, "covered": covered})
    return {"day": folder.name[:8], "counts": counts, "score": hks_score.score(gold, proposal)}


def main(argv: list[str] | None = None) -> None:
    from cutdeck.hks_gold import day_folders
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--all", required=True)
    p.add_argument("--check", action="store_true")
    p.add_argument("--holdout", action="store_true")
    p.add_argument("--quiet", choices=sorted(QUIET), default="floor", help="where the pauses come from")
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    tuning, holdout = day_folders(args.all)
    for group, folders in (("tuning", tuning), ("holdout", holdout if args.holdout else [])):
        for folder in folders:
            r = check_day(folder, args.quiet)
            print(group, json.dumps(r, ensure_ascii=False, default=str)[:1500])


if __name__ == "__main__":
    main()
