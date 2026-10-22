"""Live check: does an SRT land in Premiere on exactly the frames it names?

python -m tools.srt_roundtrip make OUT_DIR --fps 29.97   # write the two test SRTs
    (drag one onto the timeline: Subtitle, Source timecode, as PREMIERE_FACTS "UI caption placement")
python -m tools.srt_roundtrip check FILE.srt             # read the captions back and compare
python -m tools.srt_roundtrip check FILE.srt --report probe.json   # compare a saved probe report

`check` runs the panel's read-only Caption Timing probe through the helper (CutDeck panel open,
`python -m cutdeck.helper` running), takes the frame rate from the sequence itself, and compares
caption track C1 cue by cue with the frame each SRT stamp is nearest. Exit 0 only when every cue
is there, on its frame.

`make` writes `<fps>-snapped.srt` (export_job's frame-exact output) and `<fps>-raw.srt` (the same
cues unsnapped: stamps at 0.1-0.9 of a frame, a 1 ms cue, cues sharing a frame). The raw file's
mismatches show which way Premiere rounds; the snapped file must match exactly.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from fractions import Fraction
from pathlib import Path
import sys

from cutdeck.sequence_timing import PPRO_TICKS_PER_SECOND
from transcribe.subtitles import read_subtitles, write_subtitles
from transcribe.timebase import Timebase, frame_to_ms, ms_to_frame


def stress_cues(tb: Timebase) -> list[dict]:
    """Cues whose raw stamps sit at awkward places inside frames."""
    cues, at = [], 2 * tb.fps_num // tb.fps_den  # start ~2 s in
    for i, part in enumerate([0.1, 0.3, 0.45, 0.55, 0.7, 0.9] * 4):
        start = int(frame_to_ms(at, tb) + part * float(frame_to_ms(1, tb)))
        end = int(frame_to_ms(at + 12 + i % 5, tb) + (1 - part) * float(frame_to_ms(1, tb)))
        cues.append({"text": f"cue {len(cues) + 1} at {part:.2f} of a frame", "start_ms": start, "end_ms": end})
        at += 20 + i % 7
    last = cues[-1]["end_ms"] + 500
    cues.append({"text": "one millisecond cue", "start_ms": last, "end_ms": last + 1})
    cues.append({"text": "shares that frame", "start_ms": last + 1, "end_ms": last + 3})
    cues.append({"text": "after a sub-frame gap", "start_ms": last + 3 + int(frame_to_ms(1, tb) / 2), "end_ms": last + 2000})
    return cues


def timebase_of(ticks_per_frame: int) -> Timebase:
    rate = Fraction(PPRO_TICKS_PER_SECOND, ticks_per_frame)
    return Timebase(rate.numerator, rate.denominator)


def compare(srt_text: str, report: dict) -> tuple[list[str], bool]:
    tpf = int(report["ticks_per_frame"])
    tb = timebase_of(tpf)
    cues = read_subtitles(srt_text)
    tracks = report["tracks"]
    if not tracks or tracks[0].get("error"):
        return [f"no readable caption track: {tracks[0]['error'] if tracks else 'none'}"], False
    items = tracks[0]["items"]
    lines = [f"sequence {report.get('sequence_name')!r} at {tb.fps_num}/{tb.fps_den} fps: "
             f"{len(cues)} SRT cues, {len(items)} captions on C1"]
    ok = len(cues) == len(items)
    for n, (cue, item) in enumerate(zip(cues, items), 1):
        want = (ms_to_frame(cue["start_ms"], tb), ms_to_frame(cue["end_ms"], tb))
        got_ticks = (int(item["start_ticks"]), int(item["end_ticks"]))
        got = tuple(Fraction(t, tpf) for t in got_ticks)
        if got != want:
            ok = False
            lines.append(f"  cue {n}: SRT {cue['start_ms']}-{cue['end_ms']} ms names frames {want[0]}-{want[1]}, "
                         f"Premiere put it at frames {float(got[0]):g}-{float(got[1]):g}")
    if len(cues) != len(items):
        lines.append(f"  count differs by {len(cues) - len(items)}: Premiere dropped or merged cues")
    lines.append("PASS: every cue on its frame" if ok else "FAIL")
    return lines, ok


async def read_live() -> dict:
    from cutdeck.ai_backend import Backend
    reply = await Backend().premiere("run_probe", {"probe": "captiontiming"})
    if not reply["report"].get("complete"):
        raise SystemExit(f"Caption Timing probe failed: {reply['report'].get('error')}")
    return reply["report"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("make")
    make.add_argument("out_dir", type=Path)
    make.add_argument("--fps", type=float, required=True)
    check = sub.add_parser("check")
    check.add_argument("srt", type=Path)
    check.add_argument("--report", type=Path, help="saved probe report instead of reading Premiere live")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    if args.command == "make":
        cues = stress_cues(Timebase.from_decimal_fps(args.fps))
        args.out_dir.mkdir(parents=True, exist_ok=True)
        for name, fps in (("snapped", args.fps), ("raw", None)):
            path = args.out_dir / f"{args.fps:g}fps-{name}.srt"
            path.write_text(write_subtitles(cues, "srt", fps=fps), encoding="utf-8")
            print(path)
        return 0

    report = json.loads(args.report.read_text(encoding="utf-8")) if args.report else asyncio.run(read_live())
    lines, ok = compare(args.srt.read_text(encoding="utf-8-sig"), report)
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
