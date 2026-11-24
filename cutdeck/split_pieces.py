"""The question pieces of the user's split sequence, read from the saved project.

The user razors the whole broadcast at every question on one sequence (`Editing` or `Edit` in the
HKS day projects), moves each keeper up to V2 and gives it ONE label colour for the person the host
is asking (projects/hks/rules.md, "Clip label colours"); drops stay on V1. So each clip on the keeper
track is one question piece, and its colour says who answers. Premiere does not give a panel the
clip label (UXP reads labels of project items only), so this reads the SAVED .prproj: save first.

    python -m cutdeck.split_pieces --prproj "<day>.prproj" --sequence Editing --fps 25

Each piece's from/to ticks go straight into premiere_make_subsequence, premiere_paste_from
(source = the split sequence) and premiere_arrange.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cutdeck import prproj_reader, timeline_transcript
from cutdeck.sequence_timing import PPRO_TICKS_PER_SECOND

# Premiere's label slots (BE.Prefs.LabelColors.<n>), as named in the user's Premiere.
COLOURS = {0: "red", 1: "pink", 2: "purple", 3: "deep purple", 4: "blue", 5: "light blue", 6: "cyan",
           7: "teal", 8: "green", 9: "light green", 10: "yellow", 11: "orange", 12: "grey"}
# What each colour means on an HKS split (projects/hks/rules.md, user 2026-11-23).
MEANING = {"pink": "first guest", "purple": "second guest", "blue": "lawyer", "green": "host",
           "yellow": "must be in / highlight", "orange": "ending sentences", "teal": "caller",
           "light green": "insert / B-roll / cover"}


def pieces(sequence: dict, fps: float, keeper_track: int = 2) -> list[dict]:
    """One entry per clip on video track `keeper_track` (1-based), in timeline order, with its
    frame-exact ticks, colour and meaning. `after_drop`: material was dropped right before it."""
    tracks = sequence["video_tracks"]
    if len(tracks) < keeper_track:
        raise ValueError(f"{sequence['name']!r} has no V{keeper_track}: is it the split sequence?")
    tpf = round(PPRO_TICKS_PER_SECOND / fps)
    frame = lambda s: round(s * fps) * tpf  # noqa: E731  (edges are on frames)
    out, prev_end = [], None
    for n, c in enumerate(sorted(tracks[keeper_track - 1]["clips"], key=lambda c: c["start"]), 1):
        colour = COLOURS.get(c.get("label"))
        start, end = frame(c["start"]), frame(c["end"])
        out.append({"n": n, "from_ticks": str(start), "to_ticks": str(end), "label": c.get("label"),
                    "start_tc": timeline_transcript.timecode(start, tpf), "seconds": round(c["end"] - c["start"], 2),
                    "colour": colour, "meaning": MEANING.get(colour), "after_drop": prev_end is not None and start != prev_end})
        prev_end = end
    return out


def with_text(sequence: dict, found: list[dict], fps: float, chars: int = 160) -> list[dict]:
    """Adds what each piece says, from each source's one stored transcript (never re-transcribed)."""
    built = timeline_transcript.build(timeline_transcript.timeline_from_prproj(sequence, fps), limit=100000)
    for p in found:
        a, b = int(p["from_ticks"]), int(p["to_ticks"])
        text = " ".join(ln["text"] for ln in built["lines"] if a <= int(ln["start_ticks"]) < b)
        p["text"] = text[:chars]
    if built.get("missing"):
        print(f"no transcript yet for: {[m['media'] for m in built['missing']]}", file=sys.stderr)
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="The question pieces of a saved split sequence, by label colour.")
    ap.add_argument("--prproj", required=True, type=Path)
    ap.add_argument("--sequence", required=True, help="the split sequence, e.g. Editing")
    ap.add_argument("--fps", type=float, default=25.0, help="the sequence's frame rate (HKS: 25)")
    ap.add_argument("--track", type=int, default=2, help="the keeper video track, 1-based (default V2)")
    ap.add_argument("--no-text", action="store_true", help="skip the words (no transcript lookup)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    named = [s for s in prproj_reader.read_project(args.prproj)["sequences"] if s["name"] == args.sequence]
    named = [s for s in named if any(t["clips"] for t in s["video_tracks"])]
    if len(named) != 1:
        print(f"{len(named)} sequences named {args.sequence!r} have clips; need exactly one", file=sys.stderr)
        return 2
    found = pieces(named[0], args.fps, args.track)
    if not args.no_text:
        found = with_text(named[0], found, args.fps)
    if args.json:
        print(json.dumps(found, ensure_ascii=False, indent=1))
        return 0
    for p in found:
        mark = "  (after a drop)" if p["after_drop"] else ""
        who = (f"{p['colour']} = {p['meaning']}" if p["meaning"] else p["colour"]
               or (f"label slot {p['label']} (the default, no meaning)" if p["label"] is not None else "no label"))
        print(f"{p['n']:3} {p['start_tc']}  {p['seconds']:7.2f}s  {who}{mark}")
        if p.get("text"):
            print(f"      {p['text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
