"""Audit every clip edge of a saved sequence with the timeline transcript (no Premiere, no new ASR).

Per edge (through-edits excluded): F1 = sound within 20 ms of the cut (`cuts_in_sound`, severity
"sound"); F2 = F1 and the cut falls inside a word by more than that word edge's error bar
(cut_ms > cut_err_ms). Holes: sound no word covers (`holes`), and how many touch a cut.
With --base (a sequence the audited one was derived from), edges also found in the base at the
same source time (one frame) are "inherited"; the rest are the editor's own.

    python tools/cut_audit.py --prproj P --sequence S [--base-prproj P2 --base S2] --db DB --out DIR
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from cutdeck import timeline_transcript as tt
from cutdeck.prproj_reader import read_project


def sequence(prproj: str, name: str, fps: float) -> dict:
    found = [s for s in read_project(prproj)["sequences"] if s["name"] == name]
    if not found:
        raise SystemExit(f"no sequence {name!r} in {prproj}")
    return tt.timeline_from_prproj(found[0], fps)


def edge_keys(clips: list[tt.Clip], frame_ms: float) -> dict:
    """(media, side, source frame) of every non-through edge."""
    through = set()
    for a, b in zip(clips, clips[1:]):
        if a.end == b.start and a.media == b.media and a.out == b.in_ and a.speed == b.speed:
            through |= {(a.id, "out"), (b.id, "in")}
    keys = {}
    for c in clips:
        for side, src in (("in", c.in_), ("out", c.out)):
            if (c.id, side) not in through:
                keys[(c.id, side)] = (c.media, side, round(src / tt.TICKS_PER_MS / frame_ms))
    return keys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prproj", required=True)
    ap.add_argument("--sequence", required=True)
    ap.add_argument("--base-prproj")
    ap.add_argument("--base")
    ap.add_argument("--track", default="A1")
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    out = Path(args.out)
    frame_ms = 1000 / args.fps
    tl = sequence(args.prproj, args.sequence, args.fps)
    r = tt.build(tl, track=args.track, db_path=Path(args.db), out_dir=out, keep_words=True, limit=0)
    clips = r["clip_objects"]
    keys = edge_keys(clips, frame_ms)
    base = set()
    if args.base:
        _, bclips, _ = tt.audio_clips(sequence(args.base_prproj or args.prproj, args.base, args.fps), args.track)
        base = {(m, s, f + d) for m, s, f in edge_keys(bclips, frame_ms).values() for d in (-1, 0, 1)}
    own = {k for k, v in keys.items() if v not in base} if args.base else set(keys)
    loud = {(e["clip"], e["side"]): e for e in r["cuts_in_sound"]}
    f1 = {k: e for k, e in loud.items() if e.get("severity") == "sound"}
    f2 = {k: e for k, e in f1.items() if e.get("word") and e.get("cut_err_ms") is not None and e["cut_ms"] > e["cut_err_ms"]}
    tps = tt.PPRO_TICKS_PER_SECOND
    cut_at = sorted(int(c.start) for c in clips) + sorted(int(c.end) for c in clips)
    holes_at_cut = [h for h in r["holes"] if any(int(h["start_ticks"]) - tps // 50 <= t <= int(h["end_ticks"]) + tps // 50 for t in cut_at)]
    words = r["word_objects"]
    by = {}
    for w in words:
        by[w.start_by] = by.get(w.start_by, 0) + 1

    def count(sel):
        return {"all": len(sel), "own": sum(k in own for k in sel), "inherited": sum(k not in own for k in sel)}
    summary = {"sequence": args.sequence, "track": r["track"], "clips": r["clips"], "skipped": len(r["skipped"]),
               "missing": r["missing"], "sources": r["sources"], "edges": count(set(keys)),
               "sound_within_20ms_F1": count(set(f1)), "faint_tail": count({k for k, e in loud.items() if e.get("severity") == "tail"}),
               "inside_word_beyond_bar_F2": count(set(f2)),
               "holes": len(r["holes"]), "hole_s": round(sum(h["end_s"] - h["start_s"] for h in r["holes"]), 1),
               "holes_touching_a_cut": len(holes_at_cut), "untranscribed": len(r["untranscribed"]),
               "words": len(words), "word_start_placement": by}
    detail = {"F1_own": [dict(e, own=True) for k, e in f1.items() if k in own],
              "F2": [dict(e, own=k in own) for k, e in f2.items()], "holes_touching_a_cut": holes_at_cut}
    out.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() else "_" for ch in args.sequence)[:50]
    (out / f"audit-{safe}.json").write_text(json.dumps({"summary": summary, **detail}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
