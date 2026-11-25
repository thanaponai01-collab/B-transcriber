"""HKS build plan Phase 4: the long-form story-cut draft of one day, offline, and its score.

The draft is three steps on the episode sections:

1. the ``cut`` judge's keeps (``hks_judge``, task ``cut``: rules 4.2 host cuts, 4.4 content cuts,
   4.5 story openings), read as runs of consecutive kept lines of the prompt's line table
   (``hks_judge.kept_runs``), so two picked spans with no line cut between them are one keep;
2. 4.1 ``hks_tighten`` inside those keeps (pauses cut only where a cover or a legal cut point
   hides the cut);
3. the cuts that need a cover get 4.3 ``hks_covers`` candidates.

``--check`` scores the draft against the user's YT body (``hks_score``). The user keeps only 13-26 %
of the span, so "cut everything" scores high on every agreement; each number is printed beside
that baseline (``cut_all_agreement``, ``line_cut_all``, ``host_cut_all``), and keep precision
beside its chance at the same length (``chance_precision``). Reported per day:
- ``line_agreement``: per prompt line inside the scored span, kept or cut, against the user's
  keeps (a line counts as kept by the user when half of it is kept);
- ``host``: the same over the host's lines only (4.2);
- ``side_sections`` (20261120 only, 4.4): the share of the user's dropped side sections the draft
  drops too (34:56-41:09 and 47:00-49:48 of the YT cut, in source seconds).

    python -m cutdeck.hks_draft --all G:\\Me\\Works --check [--holdout]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cutdeck import hks_covers, hks_episode, hks_judge, hks_tighten

LENGTH = (900.0, 1200.0)  # s: the whole draft, 15 to 20 min (the scorer's own range counts only its span)
SIDE_SECTIONS_20261120 = ((2096.0, 2469.0), (2820.0, 2988.0))


def judge_keeps(folder: Path, out: Path = hks_judge.OUT) -> dict[str, list[tuple[float, float]]]:
    """Runs of consecutive kept lines per footage file, from the cut answer; a run never reaches
    over a hidden drop or sponsor."""
    return hks_judge.kept_runs(folder, "cut", out)


def draft(folder: Path) -> dict:
    """{"keeps", "covered", "covers", "counts"} per footage file, in source seconds."""
    ep = hks_episode.load(folder.name[:8])
    out = {}
    for media, keeps in judge_keeps(folder).items():
        f = ep["files"].get(media, {})
        path = str(folder / "1. FOOTAGE" / media)
        k, covered, n = hks_tighten.tighten(keeps, hks_tighten.pauses(path),f.get("layout", []),
                                            f.get("cut_points", []))
        stories = hks_covers.story_spans(f.get("topics", []), f.get("duration", 1e9))
        # Every cut between keeps that is not on a legal point gets the best cover candidates;
        # a cut with a candidate counts as covered (4.3 places the cover over it).
        legal = hks_tighten.legal_points(f.get("cut_points", []))
        covers, used = {}, []
        for (_, a), (b, _) in zip(k, k[1:]):
            if any(abs(b - p) <= 0.04 for p in legal) or hks_tighten.in_still(f.get("cut_points", []), a, b):
                continue
            # Best candidate whose picture no earlier cover shows, so a far run is not reused.
            c = [x for x in hks_covers.candidates(a, f.get("layout", []), stories) if x["kind"] != "hold"
                 and not any(x["source_in"] < u + hks_covers.COVER_S and u < x["source_out"] for u in used)][:3]
            if c:
                used.append(c[0]["source_in"])
                covers[round(a, 2)] = c
                if (a, b) not in covered:
                    covered.append((a, b))
        out[media] = {"keeps": k, "covered": sorted(covered), "counts": n, "covers": covers}
    return out


def _kept(t0: float, t1: float, keeps) -> float:
    return sum(max(0.0, min(t1, b) - max(t0, a)) for a, b in keeps)


def check_day(folder: Path) -> dict:
    from cutdeck import hks_score
    from cutdeck.hks_gold import read_day
    day = read_day(folder)
    gold = hks_score.gold_of(day)
    d = draft(folder)
    names = {m.lower(): m for m in d}
    proposal = hks_score.parse_proposal({
        "keeps": {g: [list(x) for x in d[names[g.lower()]]["keeps"]] for g in gold.keeps if g.lower() in names},
        "covered": {g: [list(x) for x in d[names[g.lower()]]["covered"]] for g in gold.keeps if g.lower() in names}})
    score = hks_score.score(gold, proposal)
    shown = {m: v["lines"] for m, v in hks_judge.shown_table(folder, "cut").items()}
    ep = hks_episode.load(folder.name[:8])
    agree = host_agree = n = host_n = user_cut = host_user_cut = 0
    side = []
    for g, ranges in gold.keeps.items():
        media = names.get(g.lower())
        if media is None:
            continue
        lo, hi = (x / 1000 for x in gold.span[g])
        ukeeps = [(a / 1000, b / 1000) for a, b in ranges]
        turns = ep["files"].get(media, {}).get("turns", [])
        for _, a, b, _text in shown[media]:
            if not (lo <= a and b <= hi) or b <= a:
                continue
            user = _kept(a, b, ukeeps) >= (b - a) / 2
            ours = _kept(a, b, d[media]["keeps"]) >= (b - a) / 2
            n += 1
            agree += user == ours
            user_cut += not user
            mid = (a + b) / 2
            if any(ta <= mid < tb and k == "host" for ta, tb, k in turns):
                host_n += 1
                host_agree += user == ours
                host_user_cut += not user
        if folder.name.startswith("20261120"):
            side = [round(1 - _kept(a, b, d[media]["keeps"]) / (b - a), 3) for a, b in SIDE_SECTIONS_20261120]
    kinds = [c[0]["kind"] for v in d.values() for c in v["covers"].values()]
    counts = {}
    for v in d.values():
        counts = {k: counts.get(k, 0) + v["counts"][k] for k in v["counts"]}
    length = sum(b - a for v in d.values() for a, b in v["keeps"])
    return {"day": folder.name[:8], "length_s": round(length, 1), "length_ok": LENGTH[0] <= length <= LENGTH[1],
            "kept_s": score.kept_s, "gold_kept_s": score.gold_kept_s,
            "agreement": score.agreement,
            "cut_all_agreement": round(1 - score.gold_kept_s / score.span_s, 3) if score.span_s else None,
            "keep_precision": score.keep_precision,
            "chance_precision": round(score.gold_kept_s / score.span_s, 3) if score.span_s else None,
            "keep_recall": score.keep_recall, "boundary_recall": score.boundary_recall,
            "jump_cuts": score.jump_cuts,
            "line_agreement": round(agree / n, 3) if n else None,
            "line_cut_all": round(user_cut / n, 3) if n else None,
            "covers": {k: kinds.count(k) for k in sorted(set(kinds))},
            "host": round(host_agree / host_n, 3) if host_n else None,
            "host_cut_all": round(host_user_cut / host_n, 3) if host_n else None, "tighten": counts,
            **({"side_sections": side} if side else {})}


def main(argv: list[str] | None = None) -> None:
    from cutdeck.hks_gold import day_folders
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--all", required=True)
    p.add_argument("--check", action="store_true")
    p.add_argument("--holdout", action="store_true")
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    tuning, holdout = day_folders(args.all)
    for group, folders in (("tuning", tuning), ("holdout", holdout if args.holdout else [])):
        for folder in folders:
            if not hks_judge.paths(folder, "cut")[1].exists():
                print(group, folder.name[:8], "no cut answer")
                continue
            print(group, json.dumps(check_day(folder), ensure_ascii=False))


if __name__ == "__main__":
    main()
