"""Measure the middle layer's duplicate rules on the user's finished HKS cuts (docs/SYSTEM_LAYERS.md).

1. "Is it quiet?" Four definitions in the code, each asked at the same points:
   A ffmpeg silencedetect -35 dB >= 0.3 s   (cutdeck.hks_tighten.silences; hks_judge, hks_draft)
   B VAD speech-span gaps of the transcript (store.get_speech_spans; Rough Cut's rules.silence_cuts)
   C whole-file noise floor + 6 dB, 10 ms  (cutdeck.timeline_transcript; word_cut, hks_cut_check)
   D local floor +/-500 ms + 6 dB, needs a 20 dB rise (transcribe.pipeline.word_align.snap_to_sound)
   E C or a >= 0.15 s gap between words     (cutdeck.hks_cut_check, the shipping HKS gate)
   Points: every sound edge of the user's YouTube body (should be quiet) and the middle of
   words the user kept (should not be). A point is quiet when the rule finds quiet within
   +/- REACH ms of it.
2. "What is a filler?" The config lexicon (rules.filler_cuts) and speech_clean.FILLER, scored by
   how often the user cut the words each one matches.

Reads only; tuning days only (hks_gold.TUNING), never the holdout.

    python tools/measure_middle_layer.py --root "G:\\Me\\Works" [--days 20261110 20261120] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cutdeck import hks_tighten  # noqa: E402
from cutdeck.hks_cut_check import in_word_gap  # noqa: E402
from cutdeck.hks_gold import TUNING, body, day_folders, read_day  # noqa: E402
from cutdeck.speech_clean import FILLER  # noqa: E402
from cutdeck.timeline_transcript import ENVELOPE_MS, TAIL_DB, media_sha256, noise_floor, source_words  # noqa: E402
from transcribe.db import store  # noqa: E402

RULES = "ABCDE"


def quiet_rules(t: float, reach_ms: int, sil, vad_gaps, lev, floor_c: float, words) -> dict[str, bool]:
    lo, hi = t - reach_ms / 1000, t + reach_ms / 1000
    f = int(t * 1000 // ENVELOPE_MS)
    r = reach_ms // ENVELOPE_MS
    win = lev[max(f - r, 0):f + r + 1]
    a = any(s < hi and e > lo for s, e in sil)
    b = any(s < hi and e > lo for s, e in vad_gaps)
    c = bool(len(win)) and float(win.min()) < floor_c
    ctx = lev[max(0, f - 50):f + 50]
    live = ctx[ctx > -120.0]
    floor_d = float(live.min() if len(live) else (ctx.min() if len(ctx) else 0.0))
    rise = float(lev[f:f + 15].max() - floor_d) if f < len(lev) else 0.0
    d = bool(len(win)) and rise >= 20.0 and float(win.min()) < floor_d + 6.0
    e = c or in_word_gap(words, t)
    return {"A": a, "B": b, "C": c, "D": d, "E": e}


def edges(keeps) -> list[tuple[str, float]]:
    """(media, source s) at every sound cut of the body: the out of one keep and the in of the next."""
    ks = sorted(keeps, key=lambda k: k.tl_start)
    out = []
    for prev, cur in zip(ks, ks[1:]):
        if prev.media == cur.media and abs(prev.source_out - cur.source_in) < 0.02:
            continue  # the source plays on
        out += [(prev.media, prev.source_out), (cur.media, cur.source_in)]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=r"G:\Me\Works")
    ap.add_argument("--days", nargs="*", default=list(TUNING))
    ap.add_argument("--db", default=str(ROOT / "transcriber.db"))
    ap.add_argument("--levels", default=str(ROOT / "output" / "timeline_transcripts" / "levels"))
    ap.add_argument("--reach", type=int, nargs="*", default=[40, 120])
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    db = Path(args.db)
    cfg =yaml.safe_load((ROOT / "transcribe" / "config.yaml").read_text(encoding="utf-8"))
    lexicon = {w.strip() for w in _find(cfg, "filler_lexicon")}
    rng = random.Random(0)

    tuning, _ = day_folders(args.root)
    folders = [f for f in tuning if any(f.name.startswith(d) for d in args.days)]
    points = []  # (kind, day, media, t, {reach: rules})
    fill = {"lexicon": [0, 0], "regex": [0, 0], "all": [0, 0]}  # [matched words, of them cut by the user]
    fill_words = {"lexicon": {}, "regex": {}}
    skipped = []
    for folder in folders:
        gold = read_day(folder)
        if gold.yt is None:
            skipped.append(f"{folder.name}: no YT gold ({'; '.join(gold.problems)[:120]})")
            continue
        keeps, _ = body(gold.yt)
        by_media = {}
        for k in keeps:
            by_media.setdefault(k.media, []).append(k)
        sources = {}
        for media in by_media:
            path = Path(media) if Path(media).is_absolute() else folder / "1. FOOTAGE" / media
            if not path.is_file():
                skipped.append(f"{folder.name}: missing {media}")
                continue
            got = source_words(str(path), db, Path(args.levels))
            if got is None or got[2] is None:
                skipped.append(f"{folder.name}: no transcript or levels for {path.name}")
                continue
            job_id, words, lev, _, _ = got
            conn = store.connect(db)
            try:
                spans = sorted((s.start_ms / 1000, s.end_ms / 1000) for s in store.get_speech_spans(conn, job_id)
                               if s.kind == "speech")
            finally:
                conn.close()
            gaps, prev = [], 0.0
            for s, e in spans:
                if s > prev:
                    gaps.append((prev, s))
                prev = max(prev, e)
            gaps.append((prev, float("inf")))
            sil = hks_tighten.silences(str(path))
            sources[media] = (words, lev, noise_floor(lev) + TAIL_DB, gaps, sil)
            print(f"{folder.name} {path.name}: {len(words)} words, {len(spans)} speech spans, {len(sil)} silences",
                  file=sys.stderr)
        day_edges = [(m, t) for m, t in edges(keeps) if m in sources]
        kept_words = []
        for media, ks in by_media.items():
            if media not in sources:
                continue
            words = sources[media][0]
            lo, hi = min(k.source_in for k in ks), max(k.source_out for k in ks)
            for w in words:
                mid = (w.start_ms + w.end_ms) / 2000
                if not lo <= mid <= hi:
                    continue
                kept = any(k.source_in <= mid < k.source_out for k in ks)
                t = w.text.strip()
                for name, hit in (("lexicon", t in lexicon), ("regex", bool(FILLER.match(t))), ("all", True)):
                    if hit:
                        fill[name][0] += 1
                        fill[name][1] += not kept
                        if name != "all":
                            c = fill_words[name].setdefault(t, [0, 0])
                            c[0] += 1
                            c[1] += not kept
                if kept and (w.end_ms - w.start_ms) >= 250:
                    kept_words.append((media, mid))
        mids = rng.sample(kept_words, min(len(kept_words), max(len(day_edges), 1)))
        for kind, pts in (("edge", day_edges), ("mid_word", mids)):
            for media, t in pts:
                words, lev, floor_c, gaps, sil = sources[media]
                points.append((kind, folder.name[:8], media, t,
                               {r: quiet_rules(t, r, sil, gaps, lev, floor_c, words) for r in args.reach}))

    report = {"days": sorted({p[1] for p in points}), "skipped": skipped, "reach": {}}
    for r in args.reach:
        e = [p[4][r] for p in points if p[0] == "edge"]
        m = [p[4][r] for p in points if p[0] == "mid_word"]
        report["reach"][r] = {
            "edges": len(e), "mid_words": len(m),
            "edge_quiet_pct": {k: round(100 * sum(x[k] for x in e) / max(len(e), 1), 1) for k in RULES},
            "mid_word_quiet_pct": {k: round(100 * sum(x[k] for x in m) / max(len(m), 1), 1) for k in RULES},
            "edge_agree_pct": {f"{a}{b}": round(100 * sum(x[a] == x[b] for x in e) / max(len(e), 1), 1)
                               for a, b in combinations(RULES, 2)},
        }
    report["fillers"] = {k: {"matched": v[0], "cut_by_user": v[1],
                             "cut_pct": round(100 * v[1] / max(v[0], 1), 1)} for k, v in fill.items()}
    report["filler_words"] = {k: dict(sorted(v.items(), key=lambda kv: -kv[1][0])) for k, v in fill_words.items()}
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.json:
        Path(args.json).write_text(text, encoding="utf-8")
    print(text)
    return 0


def _find(node, key):
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for v in node.values():
            got = _find(v, key)
            if got is not None:
                return got
    return None


if __name__ == "__main__":
    sys.exit(main())
