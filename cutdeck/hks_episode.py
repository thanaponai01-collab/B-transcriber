"""HKS build plan Phase 2: ``episode.json``, the analysis of one day's footage, plus step 2.3.

One folder per day, ``<out>/<yyyymmdd>/<section>.json``, read back as one dict. Every value is keyed by footage file name and given
in **source seconds of that file**, as ``hks_score`` keys keeps: 20261112 has five footage files.
Each analysis step writes only its own section, so steps run in any order and a re-run replaces
its section and nothing else:

    {"day": "20261120",
     "files": {"<file>.mp4": {
         "duration": 4529.4,
         "clock":    [[a, b], ...],       2.3  seconds with the TV clock on screen, half-open
         "tv_part":  [a, b] | null,       2.3  first clock second to the end of the last 30 s run
         "drops":    [{"start", "end", "kind", "why"}],   2.2
         "layout":   [[a, b, kind]],                      2.4
         "cut_points": [[t, kind]],                       2.5
         "turns":    [[a, b, "host" | "guest"]],          2.6
         "sponsors": [...], "stories": [...]}}}           2.7, 2.9

Phases 3-6 read only this file and the footage.

Step 2.3 (``--clock``) lifts the 1 fps clock track of ``hks_audit`` (cached, shared with the
audit). ``--check`` is its proof: on 20261120 the clock shows to 2815 s and is gone from 2825 s,
and on every tuning day each clock-on second the YT body shows at the main framing sits under a
blur (the gold blur is wider than the clock; plan step 5.1).

    python -m cutdeck.hks_episode --all G:\\Me\\Works --clock [--check] [--holdout]
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from cutdeck.hks_gold import day_folders, read_day

OUT = Path("test_projects/hks_episode")
CACHE = Path(tempfile.gettempdir()) / "hks_audit"  # the audit's clock tracks, so neither recomputes


def path_of(day: str, out: Path = OUT) -> Path:
    return out / f"{day}.json"


def _section_path(day: str, section: str, out: Path) -> Path:
    return out / day / f"{section}.json"


def load(day: str, out: Path = OUT) -> dict:
    """The whole episode: every section file of the day merged (and a pre-split ``<day>.json``)."""
    ep = {"day": day, "files": {}}
    legacy = path_of(day, out)
    if legacy.exists():
        ep["files"] = json.loads(legacy.read_text(encoding="utf-8"))["files"]
    for f in sorted((out / day).glob("*.json")) if (out / day).is_dir() else []:
        for media, value in json.loads(f.read_text(encoding="utf-8")).items():
            ep["files"].setdefault(media, {})[f.stem] = value
    return ep


def update(day: str, file: str, section: str, value, out: Path = OUT) -> dict:
    """Replace one section of one file. Each section lives in its own file
    (``<out>/<day>/<section>.json``, footage file -> value), so steps that write different
    sections never touch the same file."""
    p = _section_path(day, section, out)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    data[file] = value
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)
    return load(day, out)


def spans(flags) -> list[list[int]]:
    """Half-open second runs ``[a, b)`` where ``flags`` is true."""
    from cutdeck.hks_audit import runs
    return [[a, b] for a, b in runs(flags, True)]


def inside(spans_: list[list[float]], t: float) -> bool:
    return any(a <= t < b for a, b in spans_)


# --- 2.3 ---------------------------------------------------------------------------------------

def clock_day(folder: Path, cache: Path = CACHE, out: Path = OUT) -> dict:
    from cutdeck.hks_audit import clock_track, tv_part
    day = folder.name[:8]
    for media in sorted((folder / "1. FOOTAGE").glob("*.mp4")):
        track = clock_track(str(media), cache)
        part = tv_part(track)
        update(day, media.name, "clock", spans(track), out)
        update(day, media.name, "tv_part", None if part is None else list(part), out)
        update(day, media.name, "duration", float(len(track)), out)
    return load(day, out)


def unblurred_clock(folder: Path, ep: dict) -> list[float]:
    """YT body timeline seconds (sample midpoints) that show a clock-on source second at the main
    framing without a blur over them. The clock comes from ``ep``, not from the track."""
    from cutdeck.hks_audit import blur_samples, layers
    from cutdeck.hks_gold import _non_empty
    from cutdeck.prproj_reader import read_project

    gold = read_day(folder)
    seq = next(s for s in read_project(gold.project)["sequences"]
               if s["name"] == gold.yt.sequence and _non_empty(s))
    clocks = {name.lower(): f.get("clock", []) for name, f in ep["files"].items()}
    ls = layers(seq, set(clocks))

    def clock_of(layer, t):
        if layer.kind != "footage":
            return None  # holds and overlays: not this step's clock
        return inside(clocks[layer.media.lower()], round(layer.source_at(t)))

    start = gold.yt.hook_end or 0.0
    return [r["t"] for r in blur_samples(ls, clock_of, start, gold.yt.show_end)
            if r["state"] == "clock" and not r["blurred"]]


def check_day(folder: Path, out: Path = OUT) -> list[str]:
    """Failures of the 2.3 check for one day (empty = pass)."""
    ep = load(folder.name[:8], out)
    fails = []
    if folder.name.startswith("20261120"):
        (name, f), = ep["files"].items()
        if not inside(f["clock"], 2815) or any(inside(f["clock"], t) for t in range(2825, int(f["duration"]))):
            last = max(b for _, b in f["clock"])
            fails.append(f"20261120 clock should run to 2815 s and stop by 2825 s; last clock second {last - 1}")
    bad = unblurred_clock(folder, ep)
    if bad:
        fails.append(f"{folder.name[:8]}: {len(bad)} clock seconds shown unblurred, first at tl {bad[0]:.1f}")
    return fails


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--all", required=True, help="the folder holding the day folders")
    p.add_argument("--clock", action="store_true", help="write the clock sections (step 2.3)")
    p.add_argument("--check", action="store_true", help="run the 2.3 check")
    p.add_argument("--holdout", action="store_true", help="also the three holdout days")
    p.add_argument("--out", default=str(OUT))
    args = p.parse_args(argv)
    out = Path(args.out)
    tuning, holdout = day_folders(args.all)
    fails = []
    for folder in tuning + (holdout if args.holdout else []):
        if args.clock:
            ep = clock_day(folder, out=out)
            on = sum(b - a for f in ep["files"].values() for a, b in f["clock"])
            print(f"{folder.name[:8]}: {len(ep['files'])} files, {on} clock seconds")
        if args.check:
            day_fails = check_day(folder, out)
            print(f"{folder.name[:8]}: {'ok' if not day_fails else '; '.join(day_fails)}")
            fails += day_fails
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
