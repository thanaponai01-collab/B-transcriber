"""HKS build plan 6.1 and 6.2: the FB cut and the 1-minute square cut, picked from the long form.

Both play after the long form's own hook. The body is picked by meaning, select-only, from the
lines of the long form (``hks_judge`` tasks ``fb`` and ``minute``, which show only lines inside
the episode section ``long_form``). Length rules (the user's answers 4 and 5, 2026-11-23):

- FB: hook + body never reaches 180 s; 179.96 s is the ceiling (past cuts 168.28-179.96 s);
- 1-min: aims at 59.96 s, and 56-64 s passes.

``fit`` trims the body's last piece so the cut lands on the target, and refuses a body too short
to reach the floor.

``--prompt`` writes ``long_form`` from the user's own YT body keeps (so 6.1 is checked apart
from the Phase 4 draft) and the two prompts. ``--check`` scores the answers against the user's
FB and square bodies (``hks_gold``): precision and recall of the picked seconds, with the chance
precision at the same length, the fitted length, and whether every piece is inside the long form.

    python -m cutdeck.hks_versions --all G:\\Me\\Works --prompt
    python -m cutdeck.hks_versions --all G:\\Me\\Works --check [--holdout]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cutdeck import hks_episode, hks_judge
from cutdeck.hks_tighten import untightened

KINDS = {  # kind: (judge task, gold attribute, target total s, floor s)
    "fb": ("fb", "fb", 179.96, 168.0),
    "minute": ("minute", "square", 59.96, 56.0),
}


def merged(spans) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1] + 1e-6:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def overlap(ours, theirs) -> float:
    return sum(max(0.0, min(b, d) - max(a, c)) for a, b in merged(ours) for c, d in merged(theirs))


def fit(pieces: list[tuple[float, float]], hook: float, target: float, floor: float) -> list[tuple[float, float]]:
    """Pieces in order, the last ones trimmed or dropped so hook + body <= target; raises when the
    body cannot reach the floor."""
    out, total = [], hook
    for a, b in pieces:
        if total + (b - a) > target:
            if target - total > 0.5:
                out.append((a, a + target - total))
                total = target
            break
        out.append((a, b))
        total += b - a
    if total < floor:
        raise ValueError(f"the cut is {total:.2f} s, under the {floor} s floor")
    return out


def write_prompts(folder: Path) -> list[Path]:
    from cutdeck.hks_gold import body, read_day
    gold = read_day(folder)
    keeps, _ = body(gold.yt)
    day = folder.name[:8]
    for media in sorted({k.media for k in keeps}):
        name = next(m for m in hks_episode.load(day)["files"] if m.lower() == media.lower())
        lf = untightened([(k.source_in, k.source_out) for k in keeps if k.media == media])
        hks_episode.update(day, name, "long_form", [list(x) for x in lf])
    return [hks_judge.write_prompt(folder, task) for task, *_ in KINDS.values()]


def check_day(folder: Path) -> dict:
    from cutdeck.hks_gold import body, read_day
    gold = read_day(folder)
    ep = hks_episode.load(folder.name[:8])
    out = {"day": folder.name[:8]}
    for kind, (task, attr, target, floor) in KINDS.items():
        if not hks_judge.paths(folder, task)[1].exists():
            out[kind] = "no answer"
            continue
        picked = hks_judge.answer(folder, task)
        user = getattr(gold, attr)
        theirs, _ = body(user)
        r = {"picked_s": 0.0, "user_s": 0.0, "hit_s": 0.0, "long_form_s": 0.0, "inside": True}
        pieces = []
        for media, spans in picked.items():
            ours = [(s["start"], s["end"]) for s in spans]
            pieces += ours
            th = [(k.source_in, k.source_out) for k in theirs if k.media.lower() == media.lower()]
            lf = [tuple(x) for x in ep["files"].get(media, {}).get("long_form", [])]
            r["picked_s"] += sum(b - a for a, b in merged(ours))
            r["user_s"] += sum(b - a for a, b in merged(th))
            r["hit_s"] += overlap(ours, th)
            r["long_form_s"] += sum(b - a for a, b in lf)
            r["inside"] &= abs(overlap(ours, lf) - sum(b - a for a, b in merged(ours))) < 0.05
        hook = user.hook_end or 0.0
        try:
            fitted = fit(pieces, hook, target, floor)
            r["length"] = round(hook + sum(b - a for a, b in fitted), 2)
        except ValueError as e:
            r["length"] = str(e)
        r["precision"] = round(r["hit_s"] / r["picked_s"], 3) if r["picked_s"] else None
        r["recall"] = round(r["hit_s"] / r["user_s"], 3) if r["user_s"] else None
        r["chance"] = round(r["user_s"] / r["long_form_s"], 3) if r["long_form_s"] else None
        out[kind] = {k: round(v, 1) if isinstance(v, float) and k.endswith("_s") else v for k, v in r.items()}
    return out


def main(argv: list[str] | None = None) -> None:
    from cutdeck.hks_gold import day_folders
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--all", required=True)
    p.add_argument("--prompt", action="store_true")
    p.add_argument("--check", action="store_true")
    p.add_argument("--holdout", action="store_true")
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    tuning, holdout = day_folders(args.all)
    for group, folders in (("tuning", tuning), ("holdout", holdout if args.holdout else [])):
        for folder in folders:
            if args.prompt:
                print(group, [str(x) for x in write_prompts(folder)])
            if args.check:
                print(group, json.dumps(check_day(folder), ensure_ascii=False))


if __name__ == "__main__":
    main()
