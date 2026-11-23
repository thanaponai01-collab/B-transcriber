"""HKS reels (build plan 6.2): build the two 1080x1920 reels from the user's finished FB and square cuts.

The user's rule, read off the saved projects of every day (2026-11-23):

- ``2 FACEBOOK D<n> Copy 01`` is ``2 FACEBOOK D<n>`` minus its one ``LOGO_FOR SQUARE FRAME2.png``;
- ``4 REEL SIZE D<n>``: the square ``3 SQUARE SELECT D<n>`` nested on V1 + A1 from 0 for its whole
  length, with the frame ``1.png`` on a higher video track over the same span;
- ``5 REEL 1-3 SIZE D<n>``: the FB copy nested the same way, with the same ``1.png`` on top.

``plan`` turns a day project's offline read into the driver calls that build both reels on new
sequences (``... (CutDeck)``), never the user's. Each reel starts from a copy of the day
template's empty reel sequence, so it has the template's settings: a nest across settings can
commit and place nothing (PREMIERE_FACTS "createOverwriteItemAction(seq.getProjectItem(), ...)
across settings"). The frame goes in through ``build_sequence`` with ``into``, which sets the
still's In/Out before it places it: ``edit_clips`` ``trim_out`` on a placed PNG is BROKEN
(PREMIERE_FACTS "edit_clips trim_out on a placed PNG still").

    python -m cutdeck.hks_reels PROJECT            # print the plan
    python -m cutdeck.hks_reels PROJECT --run      # send it to the CutDeck panel
    python -m cutdeck.hks_reels --check PROJECT [--user]   # offline proof on the saved project
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from pathlib import Path

from cutdeck.sequence_timing import PPRO_TICKS_PER_SECOND

LOGO = "LOGO_FOR SQUARE FRAME2.png"
FRAME = "1.png"
FRAME_PLACES = ("1. FOOTAGE/PSD-REEL/1.png", "1. FOOTAGE/1.png")  # newer days, older days
REEL_FRAME = [1080, 1920]
MAX_FB = 179.96
SUFFIX = " (CutDeck)"
TOL = 0.02  # half a frame at 25 fps
FB_NAME = re.compile(r"2 FACEBOOK D(\d+)")


def _clips(seq: dict):
    for kind in ("video_tracks", "audio_tracks"):
        for i, track in enumerate(seq[kind]):
            for clip in track["clips"]:
                yield kind, i, clip


def _has_clips(seq: dict) -> bool:
    return any(True for _ in _clips(seq))


def length(seq: dict) -> float:
    return max((c["end"] for _, _, c in _clips(seq)), default=0.0)


def _ticks(seconds: float) -> str:
    return str(round(seconds * PPRO_TICKS_PER_SECOND))


def _full(project: dict, name: str) -> list[dict]:
    return [s for s in project["sequences"] if s["name"] == name and _has_clips(s)]


def _content(seq: dict, skip: str | None = None) -> Counter:
    """Every clip with its kind and track position, minus clips named ``skip``."""
    return Counter((kind, i, json.dumps(c, sort_keys=True)) for kind, i, c in _clips(seq) if c["name"] != skip)


def day_number(project: dict, day: int | None = None) -> int:
    days = sorted({int(m.group(1)) for s in project["sequences"]
                   if (m := FB_NAME.fullmatch(s["name"])) and _has_clips(s)})
    if day is not None:
        if day not in days:
            raise ValueError(f"no non-empty 2 FACEBOOK D{day} (days with one: {days})")
        return day
    if len(days) != 1:
        raise ValueError(f"need exactly one day with a non-empty 2 FACEBOOK D<n>, found {days}; pass --day")
    return days[0]


def _source(project: dict, name: str) -> dict:
    """The one non-empty sequence `name`, as duplicate_sequence and place_media pick it live."""
    found = _full(project, name)
    if not found:
        raise ValueError(f'no non-empty "{name}"')
    if len(found) > 1:
        raise ValueError(f'{len(found)} non-empty sequences are named "{name}"; the panel cannot tell them '
                         "apart: rename or delete the extra one in Premiere")
    return found[0]


def _empty_reel(project: dict, prefix: str, n: int) -> str:
    """The name of a day template's empty reel sequence (``<prefix> D<k>``, 1080x1920): ``D<n>``
    when one is empty, else any day's (a D2 day still carries the template's D1 blanks)."""
    pattern = re.compile(re.escape(prefix) + r" D\d+")
    names = sorted({s["name"] for s in project["sequences"] if pattern.fullmatch(s["name"])
                    and not _has_clips(s) and s.get("frame") == REEL_FRAME},
                   key=lambda name: name != f"{prefix} D{n}")
    if not names:
        raise ValueError(f'no empty 1080x1920 "{prefix} D<n>" sequence (the day template\'s) to build on')
    return names[0]


def find_frame(project_path: str | Path) -> Path | None:
    """The day's ``1.png``: ``<day>/1. FOOTAGE/PSD-REEL`` on newer days, ``<day>/1. FOOTAGE`` on older ones."""
    day = Path(project_path).parents[2]
    return next((day / p for p in FRAME_PLACES if (day / p).is_file()), None)


def _frame_build(project_path: str, reel: str, png: str, seconds: float) -> dict:
    return {"command": "build_sequence", "args": {
        "project": project_path, "base": reel, "name": reel, "into": True,
        "items": [{"id": "reel frame", "media": png, "import": True, "in_ticks": "0",
                   "out_ticks": _ticks(seconds), "at_ticks": "0", "v": 1, "a": None}]}}


def plan(project: dict, png: str | Path | None, day: int | None = None, suffix: str = SUFFIX) -> list[dict]:
    """The ordered driver calls that build both reels of one day on new sequences. Each call is
    {command, args} plus, for duplicate_sequence, `expect`: what the copy must read back live."""
    n = day_number(project, day)
    fb_name, square_name = f"2 FACEBOOK D{n}", f"3 SQUARE SELECT D{n}"
    fb, square = _source(project, fb_name), _source(project, square_name)
    if png is None:
        raise ValueError(f"no {FRAME} in the day folder ({' or '.join(FRAME_PLACES)})")
    logos = [(t, c) for t in fb["video_tracks"] for c in t["clips"] if c["name"] == LOGO]
    if len(logos) != 1:
        raise ValueError(f'"{fb_name}" has {len(logos)} {LOGO} clips, need exactly 1')
    logo_track, logo = logos[0]
    fb_copy_length = max(c["end"] for _, _, c in _clips(fb) if c is not logo)
    if fb_copy_length > MAX_FB + 1e-6:
        raise ValueError(f'"{fb_name}" without its logo runs {fb_copy_length:.2f} s, over {MAX_FB} s')
    fb_copy = f"{fb_name} Copy 01{suffix}"
    reel4, reel5 = f"4 REEL SIZE D{n}{suffix}", f"5 REEL 1-3 SIZE D{n}{suffix}"
    taken = {s["name"] for s in project["sequences"]} & {fb_copy, reel4, reel5}
    if taken:
        raise ValueError(f"already in the project: {sorted(taken)}")
    count = lambda seq, kind: sum(len(t["clips"]) for t in seq[kind])  # noqa: E731
    blank = {"width": REEL_FRAME[0], "height": REEL_FRAME[1], "video_clips": 0, "audio_clips": 0}
    png, path = str(png), str(Path(project["path"]))
    return [
        {"command": "duplicate_sequence", "args": {"sequence_name": fb_name, "result_name": fb_copy},
         "expect": {"video_clips": count(fb, "video_tracks"), "audio_clips": count(fb, "audio_tracks")}},
        {"command": "edit_clips", "args": {"sequence": fb_copy, "edits": [
            {"clip": f"V{logo_track['index'] + 1}@{_ticks(logo['start'])}", "op": "remove"}]}},
        {"command": "duplicate_sequence", "args": {"sequence_name": _empty_reel(project, "4 REEL SIZE", n),
                                                   "result_name": reel4, "empty": True}, "expect": blank},
        {"command": "place_media", "args": {"sequence": reel4, "nest": square_name, "at_ticks": "0", "v": 0, "a": 0}},
        _frame_build(path, reel4, png, length(square)),
        {"command": "duplicate_sequence", "args": {"sequence_name": _empty_reel(project, "5 REEL 1-3 SIZE", n),
                                                   "result_name": reel5, "empty": True}, "expect": blank},
        {"command": "place_media", "args": {"sequence": reel5, "nest": fb_copy, "at_ticks": "0", "v": 0, "a": 0}},
        _frame_build(path, reel5, png, fb_copy_length),
    ]


async def run(calls: list[dict], premiere=None) -> list:
    """Send the calls in order; stop at the first copy that reads back other than expected, or the
    first build that placed an item off by more than a frame."""
    if premiere is None:
        from cutdeck.ai_backend import Backend
        premiere = Backend().premiere
    results = []
    for call in calls:
        result = await premiere(call["command"], call["args"])
        results.append(result)
        print(json.dumps({"command": call["command"], "result": result}, ensure_ascii=False), flush=True)
        off = {k: (v, result.get(k)) for k, v in call.get("expect", {}).items() if result.get(k) != v}
        if off:
            raise RuntimeError(f"{call['args']['result_name']} read back {off} (expected, got): stopped")
        if call["command"] == "build_sequence" and result.get("mismatches"):
            raise RuntimeError(f"{call['args']['name']}: the frame landed off {result.get('first_mismatches')}: stopped")
    return results


# --- the offline check --------------------------------------------------------------------------

def _one(project: dict, name: str) -> dict | None:
    """The non-empty sequence `name`; identical non-empty copies count as one."""
    found = _full(project, name)
    return found[0] if found and all(_content(s) == _content(found[0]) for s in found) else None


def _check_reel(project: dict, name: str, nested_ok) -> tuple[list[str], dict | None]:
    """Problems with reel `name`: the nest on V1 + A1 from 0 for the nested sequence's whole length,
    the frame the topmost video clip over that span. Also returns the nested sequence."""
    reel = _one(project, name)
    if reel is None:
        return [f"{name}: not one non-empty sequence of that name"], None
    problems = [] if reel.get("frame") == REEL_FRAME else [f"{name}: frame {reel.get('frame')}, not {REEL_FRAME}"]
    v1 = [c for c in reel["video_tracks"][0]["clips"] if c.get("nested_sequence")] if reel["video_tracks"] else []
    if len(v1) != 1:
        return problems + [f"{name}: {len(v1)} nested clips on V1, need 1"], None
    nest = v1[0]
    inner = _one(project, nest["nested_sequence"])
    if inner is None or not nested_ok(nest["nested_sequence"]):
        return problems + [f"{name}: V1 nests {nest['nested_sequence']!r}, not the expected sequence"], None
    span = (nest["start"], nest["end"])
    if abs(span[0]) > TOL or abs(nest["source_in"]) > TOL or abs(span[1] - span[0] - length(inner)) > TOL:
        problems.append(f"{name}: nest {span[0]:.2f}-{span[1]:.2f} (in {nest['source_in']:.2f}), "
                        f"not 0-{length(inner):.2f}, the length of {nest['nested_sequence']!r}")
    a1 = reel["audio_tracks"][0]["clips"] if reel["audio_tracks"] else []
    if not any(c.get("nested_sequence") == nest["nested_sequence"]
               and abs(c["start"] - span[0]) <= TOL and abs(c["end"] - span[1]) <= TOL for c in a1):
        problems.append(f"{name}: A1 has no {nest['nested_sequence']!r} over the nest's span")
    shown = [(i, c) for i, t in enumerate(reel["video_tracks"]) for c in t["clips"]
             if not c["disabled"] and c["start"] < span[1] - TOL and c["end"] > span[0] + TOL]
    top = max((i for i, _ in shown), default=-1)
    frames = [c for i, c in shown if i == top and Path(c.get("media_path") or "").name.lower() == FRAME
              and c["start"] <= span[0] + TOL and c["end"] >= span[1] - TOL]
    if top <= 0 or not frames:
        problems.append(f"{name}: the topmost video clip over the nest is not {FRAME} covering "
                        f"{span[0]:.2f}-{span[1]:.2f} (top track V{top + 1})")
    return problems, inner


def check(project: dict, day: int | None = None, suffix: str = SUFFIX) -> list[str]:
    """Problems with both reels of a day in a saved project (empty: they pass). `suffix` " (CutDeck)"
    checks the built reels, "" the user's own."""
    n = day_number(project, day)
    fb, square = _one(project, f"2 FACEBOOK D{n}"), _one(project, f"3 SQUARE SELECT D{n}")
    if fb is None or square is None:
        return [f"day {n}: not one non-empty 2 FACEBOOK D{n} and 3 SQUARE SELECT D{n}"]
    problems, _ = _check_reel(project, f"4 REEL SIZE D{n}{suffix}", lambda nested: nested == square["name"])
    more, inner = _check_reel(project, f"5 REEL 1-3 SIZE D{n}{suffix}", lambda nested: True)
    problems += more
    if inner is not None:
        logos = sum(1 for t in fb["video_tracks"] for c in t["clips"] if c["name"] == LOGO)
        if logos != 1 or _content(inner) != _content(fb, skip=LOGO):
            problems.append(f"5 REEL 1-3 SIZE D{n}{suffix}: {inner['name']!r} is not {fb['name']!r} minus its one {LOGO}")
        if length(inner) > MAX_FB + 1e-6:
            problems.append(f"5 REEL 1-3 SIZE D{n}{suffix}: {inner['name']!r} runs {length(inner):.2f} s, over {MAX_FB}")
    return problems


def main(argv: list[str] | None = None) -> int:
    from cutdeck.prproj_reader import read_project
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project", help="the day's saved .prproj (save in Premiere first)")
    p.add_argument("--day", type=int, help="the D<n> to build (default: the one non-empty 2 FACEBOOK D<n>)")
    p.add_argument("--run", action="store_true", help="send the plan to the CutDeck panel (Premiere open on this project)")
    p.add_argument("--check", action="store_true", help="offline: check the built reels in the saved project")
    p.add_argument("--user", action="store_true", help="with --check: check the user's own reels instead")
    p.add_argument("--suffix", default=SUFFIX, help=f"appended to the new sequences' names (default {SUFFIX!r}), "
                   "e.g. to build again after a run that stopped half way")
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    path = Path(args.project).resolve()
    project = read_project(path)
    try:
        if args.check:
            problems = check(project, args.day, "" if args.user else args.suffix)
            print(json.dumps({"project": str(path), "pass": not problems, "problems": problems}, ensure_ascii=False))
            return 0 if not problems else 1
        calls = plan(project, find_frame(path), args.day, args.suffix)
    except ValueError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    if not args.run:
        print(json.dumps(calls, ensure_ascii=False, indent=1))
        return 0
    asyncio.run(run(calls))
    return 0


if __name__ == "__main__":
    sys.exit(main())
