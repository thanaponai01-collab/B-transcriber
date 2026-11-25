"""Choose the point rule of transcribe/audio/levels.py from the user's own cuts.

Positives: the sound edges of the user's finished YouTube bodies (hks_gold). Negatives: as many
mid-points of words the user kept (250 ms or longer). A point is quiet when the rule leaves a
quiet 10 ms window within ``--collar`` ms of it. J = % of edges called quiet - % of kept
mid-words called quiet. Rules are picked leave-one-day-out on the tuning days; the CI resamples
days. A held-out day is scored once, with the rule frozen beforehand.

    python tools/sweep_level_rule.py                      # sweep the tuning days
    python tools/sweep_level_rule.py --holdout 20261118 --rule 18,10,3
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from itertools import product
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from transcribe.audio import levels as lv  # noqa: E402

CACHE = ROOT / "output" / "level_rule" / "points.json"


def quiet_near(quiet: np.ndarray, times_s, collar_ms: int) -> np.ndarray:
    """Per time: is any window within ``collar_ms`` quiet?"""
    r = collar_ms // lv.ENVELOPE_MS
    q = np.concatenate(([0], np.cumsum(quiet)))
    f = (np.asarray(times_s, dtype=float) * 1000 // lv.ENVELOPE_MS).astype(int)
    lo, hi = np.clip(f - r, 0, len(quiet)), np.clip(f + r + 1, 0, len(quiet))
    return (q[hi] - q[lo]) > 0


def counts(levels, edges, mids, rule: lv.Rule, collar_ms: int) -> tuple[int, int, int, int, int]:
    """(edges quiet, edges, mid-words quiet, mid-words, sound/quiet flips) for one source."""
    quiet = ~lv.sound(levels, rule)
    e, m = quiet_near(quiet, edges, collar_ms), quiet_near(quiet, mids, collar_ms)
    return int(e.sum()), len(e), int(m.sum()), len(m), int(np.count_nonzero(np.diff(quiet.astype(np.int8))))


def j_score(c) -> float:
    return 100 * (c[0] / max(c[1], 1) - c[2] / max(c[3], 1))


def build(days: list[str], root: Path, cache: Path, db: Path, lev_dir: Path) -> dict:
    """Day -> source -> levels path, edges, kept mid-words. Cached; days already in it are kept."""
    from cutdeck.hks_gold import body, read_day
    from cutdeck.timeline_transcript import media_sha256, source_words
    from measure_middle_layer import edges as cut_edges
    data = json.loads(cache.read_text(encoding="utf-8")) if cache.is_file() else {}
    rng = random.Random(0)
    for d in days:
        if d in data:
            continue
        folder = next(root.glob(f"{d} - *"))
        gold = read_day(folder)
        if gold.yt is None:
            raise SystemExit(f"{d}: no YouTube gold ({'; '.join(gold.problems)[:200]})")
        keeps, _ = body(gold.yt)
        by_media: dict = {}
        for k in keeps:
            by_media.setdefault(k.media, []).append(k)
        srcs = {}
        for media, ks in by_media.items():
            path = Path(media) if Path(media).is_absolute() else folder / "1. FOOTAGE" / media
            got = source_words(str(path), db, lev_dir) if path.is_file() else None
            if got is None or got[2] is None:
                print(f"{d}: no transcript or levels for {media}", file=sys.stderr)
                continue
            mids = [(w.start_ms + w.end_ms) / 2000 for w in got[1] if w.end_ms - w.start_ms >= 250]
            mids = [t for t in mids if any(k.source_in <= t < k.source_out for k in ks)]
            srcs[media] = {"levels": str(lev_dir / f"{media_sha256(str(path), db)}.npy"), "mids": mids, "edges": []}
        for media, t in cut_edges(keeps):
            if media in srcs:
                srcs[media]["edges"].append(t)
        for s in srcs.values():
            s["mids"] = rng.sample(s["mids"], min(len(s["mids"]), max(len(s["edges"]), 1)))
        data[d] = srcs
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def parse_rule(text: str) -> lv.Rule:
    seed, grow, n = (text.split(",") + ["1"])[:3]
    return lv.Rule(float(seed), float(grow), int(n))


def main(argv=None) -> int:
    sys.path.insert(0, str(ROOT / "tools"))
    from cutdeck.hks_gold import HOLDOUT, TUNING
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=r"G:\Me\Works")
    ap.add_argument("--collar", type=int, default=40, help="ms; one frame at 25 fps")
    ap.add_argument("--ref", default="18,10,3", help="seed,grow[,min_seed]: the rule CIs compare against")
    ap.add_argument("--holdout", help="score this held-out day once instead of sweeping")
    ap.add_argument("--rule", action="append", default=[], help="seed,grow[,min_seed] to score on --holdout")
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--db", type=Path, default=ROOT / "transcriber.db")
    ap.add_argument("--levels", type=Path, default=ROOT / "output" / "timeline_transcripts" / "levels")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    ref = parse_rule(args.ref)
    if args.holdout:
        if args.holdout not in HOLDOUT and args.holdout in TUNING:
            raise SystemExit(f"{args.holdout} is a tuning day")
        data = build([args.holdout], Path(args.root), args.cache, args.db, args.levels)
        for rule in [ref] + [parse_rule(r) for r in args.rule]:
            c = np.sum([counts(np.load(s["levels"]), s["edges"], s["mids"], rule, args.collar)
                        for s in data[args.holdout].values()], axis=0)
            print(f"{args.holdout} {rule}: J {j_score(c):.1f}, edges quiet {100 * c[0] / c[1]:.1f}%, "
                  f"mid-words quiet {100 * c[2] / c[3]:.1f}%, flips/min {c[4] / (sum(len(np.load(s['levels'])) for s in data[args.holdout].values()) / 6000):.0f}")
        return 0

    data = build(list(TUNING), Path(args.root), args.cache, args.db, args.levels)
    days = [d for d in TUNING if d in data]
    rules = sorted({lv.Rule(float(s), float(g), n) for s, g, n in
                    product(range(6, 25, 2), range(4, 17, 2), (1, 3, 5)) if g <= s} | {ref}, key=lambda r: (r.seed_db, r.grow_db, r.min_seed))
    table = {}
    for d in days:
        for s in data[d].values():
            lev = np.load(s["levels"])
            for rule in rules:
                c = counts(lev, s["edges"], s["mids"], rule, args.collar) + (len(lev),)
                prev = table.get((rule, d), (0,) * 6)
                table[(rule, d)] = tuple(a + b for a, b in zip(prev, c))
    pooled = lambda rule, ds: j_score(np.sum([table[(rule, d)] for d in ds], axis=0))  # noqa: E731
    flips = lambda rule: (sum(table[(rule, d)][4] for d in days)  # noqa: E731
                          / (sum(table[(rule, d)][5] for d in days) / 6000))
    lodo = []
    for d in days:
        best = max(rules, key=lambda r: pooled(r, [x for x in days if x != d]))
        lodo.append((d, best, j_score(table[(best, d)])))
    rng = np.random.default_rng(0)
    samples = [list(rng.choice(days, len(days))) for _ in range(1000)]
    print(f"collar {args.collar} ms, days {days}")
    print(f"leave-one-day-out J {np.mean([x[2] for x in lodo]):.1f}; picks:")
    for d, rule, j in lodo:
        print(f"  {d} {rule} J {j:.1f}")
    print(f"top rules (pooled J, flips/min, 95% CI of J - {ref}):")
    for rule in sorted(rules, key=lambda r: -pooled(r, days))[:15] + [ref]:
        lo, hi = np.percentile([pooled(rule, ds) - pooled(ref, ds) for ds in samples], [2.5, 97.5])
        print(f"  {rule}  J {pooled(rule, days):5.1f}  flips/min {flips(rule):5.0f}  [{lo:+.1f}, {hi:+.1f}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
