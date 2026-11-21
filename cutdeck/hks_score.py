"""hks_score.py — score a proposed โหนกระแส (HKS) cut against what the user kept (the gold).

Later steps (3.1 rough cut, 4.x story cut) propose which footage to keep; this measures a
proposal against the YouTube body keeps of ``hks_gold`` (projects/hks/build-plan.md, step 0.4).

Everything is in SOURCE time, per media file, as sets of seconds: the body may repeat a source
range and its order is not always source order. The hook re-uses lines out of order, so only the
body (keeps after the hook) is gold. Gold keeps = the union of body keeps; gold drops = the gaps.

Scored span per media:
- ``body`` (default): the first to the last gold body keep. The opening title before it and the
  credits after it are the rough cut's (3.1) job, not the story cut's.
- ``file``: 0 to the file duration, so dropping the title and credits counts too.
Proposal keeps outside the span are ignored. A span limit is not an edit: drops touching it give
no boundary edge and no cut.

Times become integer milliseconds on the way in, so a 0.6 s drop is exactly 600 ms and ranges
closer than half a frame (20 ms) merge: such a gap cannot be a cut at 25 fps.

Proposal JSON (media are footage basenames, as ``hks_gold`` reports them)::

    {
      "keeps":   {"HKS Facebook 201169 Full.mp4": [[298.8, 310.28], [312.0, 400.5]]},
      "covered": {"HKS Facebook 201169 Full.mp4": [[310.28, 312.0]]}
    }

``covered`` (optional) lists the proposal's drops that other picture covers, matched to its
drops within 20 ms on both edges; any drop not listed is uncovered. Camera changes (optional,
``--camera-changes``) are ``{"<media>": [source seconds, ...]}``.

    python -m cutdeck.hks_score "G:\\Me\\Works\\20261120 - โหนกระแส" --proposal proposal.json
    python -m cutdeck.hks_score "G:\\Me\\Works\\20261120 - โหนกระแส" --baseline keep-all
    python -m cutdeck.hks_score --all G:\\Me\\Works --baseline gold [--holdout]

The holdout episodes (``hks_gold.HOLDOUT``, step 0.6) are refused unless ``--holdout`` is given, and
``--all`` prints them as their own group. ``--all`` takes a baseline only: a proposal is one day's.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from dataclasses import dataclass, field

from cutdeck.hks_gold import DayGold, body, day_folders, is_holdout, read_day

MS = 1000
MERGE = 20  # ms; half a 25 fps frame
BOUNDARY_TOL = 500  # ms
CAMERA_TOL = 120  # ms
CLASSES = (("<0.6s", 0, 600), ("0.6-3s", 600, 3000), ("3-15s", 3000, 15000), (">=15s", 15000, None))
LENGTH_RANGE = (900.0, 1200.0)

Ranges = list[tuple[int, int]]  # sorted, merged, in ms


@dataclass(frozen=True)
class Proposal:
    keeps: dict[str, Ranges]
    covered: dict[str, Ranges] = field(default_factory=dict)


@dataclass(frozen=True)
class Gold:
    span: dict[str, tuple[int, int]]
    keeps: dict[str, Ranges]


@dataclass(frozen=True)
class ClassScore:
    name: str
    proposed: int  # proposed drops of this length
    hits: int  # ... with >= 50 % inside gold drops
    precision: float | None
    gold: int  # gold drops of this length
    found: int  # ... with >= 50 % dropped by the proposal
    recall: float | None


@dataclass(frozen=True)
class Score:
    span: str
    span_s: float
    kept_s: float  # proposal, inside the span
    gold_kept_s: float
    agreement: float | None
    keep_precision: float | None
    keep_recall: float | None
    proposed_edges: int
    gold_edges: int
    edge_hits: int
    boundary_precision: float | None
    boundary_recall: float | None
    classes: tuple[ClassScore, ...]
    jump_cuts: int
    length_range: tuple[float, float]
    length_in_range: bool

    def table(self) -> str:
        pct = _pct
        lo, hi = self.length_range
        lines = [
            f"span ({self.span})        {self.span_s:.2f} s",
            f"kept / gold kept     {self.kept_s:.2f} s / {self.gold_kept_s:.2f} s",
            f"agreement            {pct(self.agreement)}",
            f"keep precision       {pct(self.keep_precision)}",
            f"keep recall          {pct(self.keep_recall)}",
            f"boundary (0.5 s)     hits {self.edge_hits} of {self.proposed_edges} proposed, "
            f"{self.gold_edges} gold: precision {pct(self.boundary_precision)}, "
            f"recall {pct(self.boundary_recall)}",
            "class      proposed  hits  precision  gold  found  recall",
        ]
        lines += [f"{c.name:<10} {c.proposed:>8} {c.hits:>5} {pct(c.precision):>10} "
                  f"{c.gold:>5} {c.found:>6} {pct(c.recall):>7}" for c in self.classes]
        lines += [f"jump cuts            {self.jump_cuts}",
                  f"length in {lo:.0f}-{hi:.0f} s  {self.length_in_range} ({self.kept_s:.2f} s)"]
        return "\n".join(lines)


def _pct(x: float | None) -> str:
    return "None" if x is None else f"{100 * x:.2f}%"


# --- intervals (integer ms) --------------------------------------------------------------------

def _ms(seconds: float) -> int:
    return round(seconds * MS)


def _merge(ranges) -> Ranges:
    out: list[list[int]] = []
    for a, b in sorted(ranges):
        if b <= a:
            continue
        if out and a - out[-1][1] <= MERGE:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def _clip(ranges: Ranges, lo: int, hi: int) -> Ranges:
    return [(max(a, lo), min(b, hi)) for a, b in ranges if min(b, hi) > max(a, lo)]


def _gaps(keeps: Ranges, lo: int, hi: int) -> Ranges:
    out, at = [], lo
    for a, b in keeps:
        if a > at:
            out.append((at, a))
        at = max(at, b)
    if hi > at:
        out.append((at, hi))
    return out


def _overlap(xs: Ranges, ys: Ranges) -> int:
    total = i = j = 0
    while i < len(xs) and j < len(ys):
        total += max(0, min(xs[i][1], ys[j][1]) - max(xs[i][0], ys[j][0]))
        if xs[i][1] < ys[j][1]:
            i += 1
        else:
            j += 1
    return total


def _length(ranges: Ranges) -> int:
    return sum(b - a for a, b in ranges)


def _matched(xs: list[int], ys: list[int], tol: int) -> int:
    """Pairs within ``tol``, each point used once (greedy on sorted points is optimal in 1-D)."""
    xs, ys = sorted(xs), sorted(ys)
    hits = i = j = 0
    while i < len(xs) and j < len(ys):
        if abs(xs[i] - ys[j]) <= tol:
            hits, i, j = hits + 1, i + 1, j + 1
        elif xs[i] < ys[j]:
            i += 1
        else:
            j += 1
    return hits


def _ratio(n: int, d: int) -> float | None:
    return None if d == 0 else n / d


def _cls(length: int) -> str:
    return next(name for name, lo, hi in CLASSES if length >= lo and (hi is None or length < hi))


# --- scoring -----------------------------------------------------------------------------------

def score(gold: Gold, proposal: Proposal, *, span_name: str = "body",
          camera_changes: dict[str, list[float]] | None = None,
          length_range: tuple[float, float] = LENGTH_RANGE) -> Score:
    unknown = set(proposal.keeps) - set(gold.span)
    if unknown:
        raise ValueError(f"proposal media not in the scored span: {sorted(unknown)}")
    cams = {m: [_ms(t) for t in ts] for m, ts in (camera_changes or {}).items()}
    span = kk = dd = kept = gold_kept = 0
    p_edges = g_edges = hits = jumps = 0
    by_class = {name: [0, 0, 0, 0] for name, _, _ in CLASSES}  # proposed, hits, gold, found
    for media, (lo, hi) in gold.span.items():
        gk = _clip(_merge(gold.keeps.get(media, [])), lo, hi)
        pk = _clip(_merge(proposal.keeps.get(media, [])), lo, hi)
        gd, pd = _gaps(gk, lo, hi), _gaps(pk, lo, hi)
        span += hi - lo
        kept += _length(pk)
        gold_kept += _length(gk)
        kk += _overlap(pk, gk)
        dd += _overlap(pd, gd)

        for side in (0, 1):  # drop starts match drop starts, ends match ends
            pe = [d[side] for d in pd if lo < d[side] < hi]
            ge = [d[side] for d in gd if lo < d[side] < hi]
            p_edges, g_edges = p_edges + len(pe), g_edges + len(ge)
            hits += _matched(pe, ge, BOUNDARY_TOL)

        for d in pd:
            c = by_class[_cls(d[1] - d[0])]
            c[0] += 1
            c[1] += 2 * _overlap([d], gd) >= d[1] - d[0]
        for d in gd:
            c = by_class[_cls(d[1] - d[0])]
            c[2] += 1
            c[3] += 2 * _overlap([d], pd) >= d[1] - d[0]

        covered = proposal.covered.get(media, [])
        for a, b in pd:
            if a == lo or b == hi:
                continue  # not between two keeps: no cut point
            if any(abs(a - x) <= MERGE and abs(b - y) <= MERGE for x, y in covered):
                continue
            if any(abs(t - a) <= CAMERA_TOL or abs(t - b) <= CAMERA_TOL for t in cams.get(media, [])):
                continue
            jumps += 1

    kept_s = kept / MS
    return Score(
        span=span_name,
        span_s=span / MS,
        kept_s=kept_s,
        gold_kept_s=gold_kept / MS,
        agreement=_ratio(kk + dd, span),
        keep_precision=_ratio(kk, kept),
        keep_recall=_ratio(kk, gold_kept),
        proposed_edges=p_edges,
        gold_edges=g_edges,
        edge_hits=hits,
        boundary_precision=_ratio(hits, p_edges),
        boundary_recall=_ratio(hits, g_edges),
        classes=tuple(ClassScore(name, p, h, _ratio(h, p), g, f, _ratio(f, g))
                      for name, (p, h, g, f) in by_class.items()),
        jump_cuts=jumps,
        length_range=length_range,
        length_in_range=length_range[0] <= kept_s <= length_range[1],
    )


# --- gold and the two built-in proposals ---------------------------------------------------------

def gold_of(day: DayGold, span: str = "body") -> Gold:
    if day.yt is None:
        raise ValueError(f"no YouTube gold: {'; '.join(day.problems)}")
    keeps: dict[str, list] = {}
    for r in body(day.yt)[0]:
        keeps.setdefault(r.media, []).append((_ms(r.source_in), _ms(r.source_out)))
    merged = {m: _merge(rs) for m, rs in keeps.items()}
    if span == "body":
        spans = {m: (rs[0][0], rs[-1][1]) for m, rs in merged.items()}
    elif span == "file":
        missing = [m for m in day.footage if day.durations.get(m) is None]
        if missing:
            raise ValueError(f"span='file' needs durations; none for {missing}")
        spans = {m: (0, _ms(day.durations[m])) for m in day.footage}
    else:
        raise ValueError(f"span must be 'body' or 'file', not {span!r}")
    return Gold(spans, merged)


def keep_all(gold: Gold) -> Proposal:
    return Proposal({m: [s] for m, s in gold.span.items()})


def gold_proposal(day: DayGold, gold: Gold) -> Proposal:
    """The gold as a proposal. A drop is uncovered only when hks_gold has an uncovered cut whose
    source gap ``(next.source_in - jump, next.source_in)`` is that drop; a gap with no cut (a muted
    censor piece at the same sync) or a cut back in source time is not a jump cut here."""
    keeps, cuts = body(day.yt)
    uncovered: dict[str, list[tuple[int, int]]] = {}
    for c in cuts:
        if c.covered or c.jump is None or c.jump <= 0:
            continue
        nxt = min(keeps, key=lambda k: abs(k.tl_start - c.tl))
        uncovered.setdefault(nxt.media, []).append((_ms(nxt.source_in - c.jump), _ms(nxt.source_in)))
    covered = {}
    for m, (lo, hi) in gold.span.items():
        covered[m] = [(a, b) for a, b in _gaps(gold.keeps.get(m, []), lo, hi)
                      if not any(abs(a - x) <= MERGE and abs(b - y) <= MERGE
                                 for x, y in uncovered.get(m, []))]
    return Proposal(dict(gold.keeps), covered)


def parse_proposal(data: dict) -> Proposal:
    """The JSON shape in the module docstring -> Proposal."""
    def ranges(section: str) -> dict[str, Ranges]:
        out = {}
        for media, rs in (data.get(section) or {}).items():
            bad = [r for r in rs if len(r) != 2 or not r[0] < r[1]]
            if bad:
                raise ValueError(f"{section}[{media!r}]: ranges must be [in, out] with in < out: {bad[:3]}")
            out[media] = _merge((_ms(a), _ms(b)) for a, b in rs)
        return out
    if "keeps" not in data:
        raise ValueError("proposal JSON needs a 'keeps' object")
    return Proposal(ranges("keeps"), ranges("covered"))


def _baseline(name: str, day: DayGold, gold: Gold) -> Proposal:
    return keep_all(gold) if name == "keep-all" else gold_proposal(day, gold)


def group_table(title: str, folders: list, baseline: str, span: str) -> str:
    """One row per day folder for a built-in proposal, then the mean of the rows."""
    cols = ("agreement", "keep_precision", "keep_recall", "boundary_recall")
    lines = [f"## {title} ({len(folders)} episodes)", "episode  | " + " | ".join(cols) + " | jump cuts"]
    scores = []
    for folder in folders:
        day = read_day(folder)
        gold = gold_of(day, span)
        scores.append(score(gold, _baseline(baseline, day, gold), span_name=span))
        lines.append(f"{folder.name[:8]} | " + " | ".join(_pct(getattr(scores[-1], c)) for c in cols)
                     + f" | {scores[-1].jump_cuts}")
    means = []
    for c in cols:
        values = [getattr(s, c) for s in scores if getattr(s, c) is not None]
        means.append(_pct(sum(values) / len(values) if values else None))
    return "\n".join([*lines, "mean     | " + " | ".join(means) + f" | {sum(s.jump_cuts for s in scores)} (sum)"])


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Score a proposed HKS cut against the user's gold.")
    p.add_argument("folder", help="a day folder, or with --all the folder that holds them")
    p.add_argument("--all", action="store_true", help="one row per tuning-set day (baselines only)")
    p.add_argument("--holdout", action="store_true",
                   help="allow a holdout day; with --all, add the holdout group (end-of-step scoring only)")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--proposal", help="proposal JSON (shape in the module docstring)")
    src.add_argument("--baseline", choices=("keep-all", "gold"))
    p.add_argument("--span", choices=("body", "file"), default="body")
    p.add_argument("--camera-changes", help='JSON {"<media>": [source seconds, ...]}')
    p.add_argument("--length-range", nargs=2, type=float, default=LENGTH_RANGE, metavar=("MIN", "MAX"))
    p.add_argument("--json", action="store_true", help="print the score as JSON")
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    if args.all:
        if not args.baseline:
            p.error("--all scores a baseline; a proposal belongs to one day folder")
        tuning, held = day_folders(args.folder)
        print(group_table("Tuning set", tuning, args.baseline, args.span))
        if args.holdout:
            print("\n" + group_table("Holdout", held, args.baseline, args.span))
        return
    if is_holdout(args.folder) and not args.holdout:
        p.error(f"{args.folder} is a holdout episode; pass --holdout to score it")

    day = read_day(args.folder)
    gold = gold_of(day, args.span)
    if args.proposal:
        with open(args.proposal, encoding="utf-8") as f:
            proposal = parse_proposal(json.load(f))
    else:
        proposal = _baseline(args.baseline, day, gold)
    cams = None
    if args.camera_changes:
        with open(args.camera_changes, encoding="utf-8") as f:
            cams = json.load(f)
    s = score(gold, proposal, span_name=args.span, camera_changes=cams,
              length_range=tuple(args.length_range))
    print(json.dumps(dataclasses.asdict(s), ensure_ascii=False, indent=2) if args.json else s.table())


if __name__ == "__main__":
    main()
