"""Calibrate plan_pieces' piece edges against an editor's own cut (offline, saved .prproj).

python scripts/timeline_listen/calibrate_edges.py PROJECT SEQUENCE MEDIA_FRAGMENT [--rough ROUGH_SEQUENCE] [--from S --to S]

For every enabled clip of MEDIA on the cut's first audio track (deduplicated by source span), the
planner places a piece for the words inside it and its In/Out are compared with the editor's.
With --rough, edges that sit within a frame of an edge of that rough cut (same source) are
reported apart: they may be the Rough Cut's choice, not the editor's ear. Each edge is also
classified by the audio at the editor's edge (sound or quiet) and whether it is inside a word.
Needs the source transcribed in the store (transcribe(media_path)).
"""
from __future__ import annotations

import argparse
import statistics
from pathlib import Path

from cutdeck import timeline_transcript as tt, word_cut
from cutdeck.prproj_reader import read_project
from transcribe.audio import levels as lv
from transcribe.db import store

TPF = 8467200000  # 30 fps; the cuts measured were all 30 fps
T = tt.TICKS_PER_MS


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("project"); ap.add_argument("sequence"); ap.add_argument("media")
    ap.add_argument("--rough"); ap.add_argument("--from", dest="lo", type=float, default=0.0)
    ap.add_argument("--to", dest="hi", type=float, default=1e9)
    args = ap.parse_args()
    seqs = {s["name"]: s for s in read_project(args.project)["sequences"]}
    clips = [c for c in seqs[args.sequence]["audio_tracks"][0]["clips"]
             if args.media in (c.get("media_path") or "") and not c["disabled"] and args.lo <= c["start"] <= args.hi]
    clips = list({(round(c["source_in"], 3), round(c["source_out"], 3)): c for c in clips}.values())
    media = clips[0]["media_path"]
    rough_edges = []
    if args.rough:
        rough_edges = sorted({round(e * 1000) for c in seqs[args.rough]["audio_tracks"][0]["clips"]
                              if args.media in (c.get("media_path") or "") for e in (c["source_in"], c["source_out"])})
    job, words, levels = tt.source_words(media, store.resolve_db_path({"store": {"path": "transcriber.db"}}),
                                            Path("output/timeline_transcripts/levels"))[:3]
    over = lv.over(levels, lv.QUIET)
    lvl = lambda m, t: float(over[max(int(t / T // 10) - 2, 0):int(t / T // 10) + 2].max())  # noqa: E731
    src = [tt.TimelineWord(w.text, w.start_ms * T, w.end_ms * T, "S", media, w.start_ms, w.end_ms, w.cue, None) for w in words]
    near_rough = lambda ms: any(abs(ms - e) <= 34 for e in rough_edges)  # noqa: E731
    rows = []
    for c in clips:
        i0, i1 = c["source_in"] * 1000, c["source_out"] * 1000
        k = [n for n, w in enumerate(src) if w.src_start_ms >= i0 - 40 and w.src_end_ms <= i1 + 40]
        if not k:
            continue
        for pad, wordless in ((120, 0), (60, 0), (60, 600)):
            p = word_cut.plan_pieces(src, [{"word_range": [k[0], k[-1]]}], TPF, {media: words}, lvl, pad, wordless,
                                     pad_in_ms=pad)[0]  # one pad both sides, as these numbers were measured
            for side, owner, planned in (("in", i0, int(p["in_ticks"]) / T), ("out", i1, int(p["out_ticks"]) / T)):
                rows.append({"setting": (pad, wordless), "side": side, "diff": abs(owner - planned), "rough": near_rough(owner),
                             "sound": lvl(media, owner * T) >= 0,
                             "inword": any(w.start_ms + 20 < owner < w.end_ms - 20 for w in words)})
    print(f"{args.sequence}: {len(clips)} pieces (deduplicated), rough-cut edges known: {bool(rough_edges)}")
    for setting in ((120, 0), (60, 0), (60, 600)):
        for group, keep in (("all edges", lambda r: True), ("not on a rough-cut edge", lambda r: not r["rough"])):
            d = [r["diff"] for r in rows if r["setting"] == setting and keep(r)]
            if d:
                print(f"  pad {setting[0]:3} wordless {setting[1]:3} | {group:24} | edges {len(d):4} | within 1 frame "
                      f"{sum(x <= 34 for x in d):4} | within 100 ms {sum(x <= 100 for x in d):4} | off >200 ms {sum(x > 200 for x in d):3}")
    base = [r for r in rows if r["setting"] == (60, 0)]
    print(f"  owner edges on a rough-cut edge: {sum(r['rough'] for r in base)} of {len(base)}")
    big = [r for r in base if r["diff"] > 200]
    print(f"  misses >200 ms at pad 60: {len(big)}; inside a word {sum(r['inword'] for r in big)}, "
          f"sound at the owner's edge {sum(r['sound'] for r in big)}, on a rough-cut edge {sum(r['rough'] for r in big)}")


if __name__ == "__main__":
    main()
