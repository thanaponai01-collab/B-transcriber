"""HKS build plan 4.3: cover candidates for every cut a draft cannot leave bare.

A cut needs a cover unless it sits on a legal cut point (2.5: a camera change, an inset camera
change, or under a still; the user's rule of 2026-11-23). For each one, candidates in the
user's order of preference (rule 6 of ``rules.md``, answer 3 of the audit):

1. ``same_moment``: news-clip or full-frame footage picture (``layout`` 2.4) of the same story
   within SAME_MOMENT_S of the cut in source time, nearest first;
2. ``same_story``: any other such picture of the same story (``topics`` 2.9: a story runs from
   its first topic start to the next story's);
3. ``hold``: a frame hold of a story picture, the fallback. Listener shots come from the user's
   ``Backup`` pool, which a draft does not have yet, so none are proposed (plan 4.3, Open).

Each candidate is a source range of COVER_S seconds. Film damage goes on every B-roll cover and a
news-window clip is zoomed to fill the width (the finishing steps place both).

``--check`` is the recall of the user's own covers: for every cover clip in the YT body
(``hks_gold`` covers), whether its source lies in the picture pool the finder draws from for its
story. Covers from studio picture (listener shots) are counted apart: the finder cannot see them.

    python -m cutdeck.hks_covers --all G:\\Me\\Works --check [--holdout]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cutdeck import hks_episode

COVER_S = 2.0      # s of cover picture per cut
SAME_MOMENT_S = 30.0  # s: picture this close to the cut in source is "the same moment"; further is "same story"
POOL_KINDS = ("clip", "footage")
TOL = 1.0          # s: a gold cover counts as in the pool when its middle is this close to a pool second


def story_spans(topics: list[dict], end: float) -> list[tuple[float, float, int]]:
    """(start, end, story) per story from the topic starts."""
    firsts: dict[int, float] = {}
    for t in topics:
        firsts.setdefault(t["story"], t["start"])
    starts = sorted((s, k) for k, s in firsts.items())
    return [(s, starts[i + 1][0] if i + 1 < len(starts) else end, k) for i, (s, k) in enumerate(starts)]


def story_at(stories, t: float) -> int | None:
    return next((k for a, b, k in stories if a <= t < b), None)


def pool(layout: list, stories, story: int | None) -> list[tuple[float, float]]:
    """Clip and footage picture runs inside that story."""
    if story is None:
        return []
    out = []
    for a, b, k in stories:
        if k != story:
            continue
        out += [(max(a, la), min(b, lb)) for la, lb, kind in layout if kind in POOL_KINDS and la < b and lb > a]
    return [(a, b) for a, b in out if b - a >= COVER_S]


def candidates(cut: float, layout: list, stories) -> list[dict]:
    """Cover candidates for a cut at source time ``cut``, best first."""
    runs = pool(layout, stories, story_at(stories, cut))
    if not runs:
        return []
    def dist(r):
        a, b = r
        return 0.0 if a <= cut < b else min(abs(cut - a), abs(cut - b))
    ranked = sorted(runs, key=dist)
    out = []
    for a, b in ranked:
        s = min(max(cut - COVER_S / 2, a), b - COVER_S)
        out.append({"kind": "same_moment" if dist((a, b)) <= SAME_MOMENT_S else "same_story",
                    "source_in": round(s, 2), "source_out": round(s + COVER_S, 2)})
    a, b = ranked[0]
    out.append({"kind": "hold", "source_in": round((a + b) / 2, 2), "source_out": round((a + b) / 2, 2)})
    return out


def check_day(folder: Path) -> dict:
    from cutdeck.hks_gold import body, read_day
    gold = read_day(folder)
    ep = hks_episode.load(folder.name[:8])
    keeps, _ = body(gold.yt)
    first = keeps[0].tl_start if keeps else 0.0
    found = studio = missing = total = 0
    examples = []
    for c in gold.yt.covers:
        if c.tl_start < first:
            continue  # the hook
        f = next((v for k, v in ep["files"].items() if k.lower() == c.media.lower()), None)
        if f is None:
            continue  # a cover from a file that is not footage (stills, graphics)
        total += 1
        layout, topics = f.get("layout", []), f.get("topics", [])
        mid = (c.source_in + c.source_out) / 2
        kind = next((k for a, b, k in layout if a <= mid < b), None)
        # The story the cover is used in: the story of the dialogue under it (the keep at that time).
        under = next((k for k in gold.yt.keeps if k.tl_start <= (c.tl_start + c.tl_end) / 2 < k.tl_end), None)
        stories = story_spans(topics, f.get("duration", 1e9))
        story = story_at(stories, under.source_in if under else mid)
        runs = pool(layout, stories, story)
        if kind not in POOL_KINDS:
            studio += 1
        elif any(a - TOL <= mid <= b + TOL for a, b in runs):
            found += 1
        else:
            missing += 1
            if len(examples) < 5:
                examples.append(round(mid, 1))
    pickable = total - studio
    return {"day": folder.name[:8], "covers": total, "studio_or_unknown": studio, "in_pool": found,
            "recall": round(found / pickable, 3) if pickable else None, "missed_at": examples}


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
            print(group, json.dumps(check_day(folder), ensure_ascii=False))


if __name__ == "__main__":
    main()
