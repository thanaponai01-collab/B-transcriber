"""HKS build plan 3.1: the rough cut's drop list, per footage file.

Drops = the break finder's ``drops`` (2.2: opening, bumpers, clock-off runs, credits; the user's
rule of 2026-11-23 drops every clock-off run) plus the ``sponsors`` (2.7) the user approved. A
sponsor is approved when its line ids are listed in ``<judge dir>/<day>/sponsors.approved.json``
(``{"approved": ["L0148", ...]}``, the ``from`` id of each span), or all of them with
``--all-sponsors``. Overlapping drops merge.

The drops go to the panel's ``apply_cuts`` on a copy (live, ⚑). ``--check`` is the offline proof:
- 20261120, the only day with an ``Edit`` sequence: every boundary of the user's drops within
  0.5 s of a boundary of ours, and ours has no boundary the user lacks;
- every day: no dropped second is kept in the YT cut (the user's ``hks_gold`` keeps), except the
  20261001 flood-map runs the user keeps (the rule drops them; the user un-drops them in review).

    python -m cutdeck.hks_rough --all G:\\Me\\Works --check [--all-sponsors] [--holdout]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cutdeck import hks_episode
from cutdeck.hks_judge import OUT as JUDGE_OUT

TOL = 0.5  # s per boundary on 20261120


def merged(spans) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1] + 1e-6:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def approved_ids(day: str, judge_dir: Path = JUDGE_OUT) -> set[str] | None:
    p = judge_dir / day / "sponsors.approved.json"
    return set(json.loads(p.read_text(encoding="utf-8"))["approved"]) if p.exists() else None


def drop_list(ep: dict, media: str, approved: set[str] | None, all_sponsors: bool = False) -> list[tuple[float, float]]:
    f = ep["files"].get(media, {})
    spans = [(d["start"], d["end"]) for d in f.get("drops", [])]
    spans += [(s["start"], s["end"]) for s in f.get("sponsors", [])
              if all_sponsors or (approved is not None and s["from"] in approved)]
    return merged(spans)


def _kept(drops, keeps) -> float:
    return sum(max(0.0, min(b, kb) - max(a, ka)) for a, b in drops for ka, kb in keeps)


def check_day(folder: Path, all_sponsors: bool = False) -> dict:
    from cutdeck.hks_gold import read_day
    day = folder.name[:8]
    ep = hks_episode.load(day)
    gold = read_day(folder)
    approved = approved_ids(day)
    r = {"day": day, "files": {}}
    for media in ep["files"]:
        drops = drop_list(ep, media, approved, all_sponsors)
        keeps = [(k.source_in, k.source_out) for k in gold.yt.keeps if k.media.lower() == media.lower()]
        r["files"][media] = {"drops": len(drops), "dropped_s": round(sum(b - a for a, b in drops), 1),
                             "kept_in_yt_s": round(_kept(drops, keeps), 2)}
        if gold.edit_drops is not None:
            ours = sorted({x for d in drops for x in d})
            theirs = sorted({x for d in gold.edit_drops for x in d})
            r["files"][media]["edit_missed"] = [x for x in theirs if not any(abs(x - y) <= TOL for y in ours)]
            r["files"][media]["edit_extra"] = [x for x in ours if not any(abs(x - y) <= TOL for y in theirs)]
    return r


def main(argv: list[str] | None = None) -> None:
    from cutdeck.hks_gold import day_folders
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--all", required=True)
    p.add_argument("--check", action="store_true")
    p.add_argument("--all-sponsors", action="store_true")
    p.add_argument("--holdout", action="store_true")
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    tuning, holdout = day_folders(args.all)
    for group, folders in (("tuning", tuning), ("holdout", holdout if args.holdout else [])):
        for folder in folders:
            print(group, json.dumps(check_day(folder, args.all_sponsors), ensure_ascii=False))


if __name__ == "__main__":
    main()
