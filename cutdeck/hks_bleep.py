"""HKS build plan 5.3: bleep proposals on swear words in kept speech, for the user to approve.

A proposal is a swear-list match in the word transcript (``hks_words``, 2.1) whose middle lies in
a keep, as a source range ``[start, end, word]``; the finishing step lays ``CENSORED SOUND
EFFECT.mp4`` over it on A2. The list is fixed before the first run: strong words only, not the
rude pronouns มึง / กู, which the show airs.

``--check`` isolates 5.3 from the cut: it proposes inside the user's own YT body keeps, with
every gap under 3 s closed (the story cut before tightening: the user cuts a bleeped word out), and
matches the proposals to the user's bleeps (the ``CENSORED SOUND EFFECT`` clips of the saved YT
sequence after the hook, mapped to source through the keep under them) within TOL s. Reported
per day: proposals, gold bleeps, hits, and precision (the bar the plan names).

The known limit (2026-11-23): the one swear the user bleeped on 20261120 (source 1693.00-1693.24)
is in no local model's transcript. The Thai medium CT2 model, Systran large-v3 and the Thai
large-v3 CT2 all skip it, with or without a swear prompt, so it cannot be found from words.

    python -m cutdeck.hks_bleep --all G:\\Me\\Works --check [--holdout]
"""
from __future__ import annotations

import argparse
import json
import ntpath
import re
import sys
from pathlib import Path

from cutdeck.hks_judge import WORDS, words_of

# Thai is written without spaces, so a swear is a pattern, not a substring: the first run (all 21
# proposals false) matched สัตว์ "animal", ผู้เชี่ยวชาญ "expert" and ขี้เหี้ยว. สัตว์ is a swear
# only after ไอ้; เหี้ย / เชี่ย not when ว follows (เหี้ยว, เชี่ยวชาญ).
SWEARS = (r"ไอ้สัตว์", r"(?<!ขี้)เหี้ย(?!ว)", r"เชี่ย(?!ว)", r"สัส", r"ควย", r"เย็ด", r"ชิบหาย", r"แม่ง")
SFX = "censored sound effect.mp4"
TOL = 0.5  # s


def matches(words: list[list]) -> list[tuple[float, float, str]]:
    """Every swear-list match in the word pieces, as (start, end, word); a match may span pieces."""
    text, owner = "", []
    for i, w in enumerate(words):
        text += w[2]
        owner += [i] * len(w[2])
    out = []
    for pattern in SWEARS:
        for m in re.finditer(pattern, text):
            a, b = owner[m.start()], owner[m.end() - 1]
            out.append((words[a][0], words[b][1], m.group()))
    return sorted(set(out))


def proposals(words: list[list], keeps: list[tuple[float, float]]) -> list[tuple[float, float, str]]:
    return [m for m in matches(words) if any(a <= (m[0] + m[1]) / 2 < b for a, b in keeps)]


def gold_bleeps(folder: Path) -> dict[str, list[float]]:
    """Source second of each user bleep in the YT body, per footage file."""
    from cutdeck.hks_build import _sequence
    from cutdeck.hks_gold import read_day
    from cutdeck.prproj_reader import read_project
    gold = read_day(folder)
    seq = _sequence(read_project(gold.project), gold.yt.sequence)
    out: dict[str, list[float]] = {}
    for track in seq["audio_tracks"]:
        for c in track["clips"]:
            if ntpath.basename(c.get("media_path") or "").lower() != SFX or c["disabled"]:
                continue
            if gold.yt.hook_end is not None and c["start"] < gold.yt.hook_end:
                continue
            # The user cuts the swear out and lays the bleep in the gap: it starts on a keep's end.
            k = next((k for k in gold.yt.keeps if k.tl_start <= c["start"] <= k.tl_end + 0.04), None)
            if k is not None:
                out.setdefault(k.media, []).append(round(k.source_in + c["start"] - k.tl_start, 2))
    return out


def check_day(folder: Path, words_dir: Path = WORDS) -> dict:
    from cutdeck.hks_gold import body, read_day
    gold = read_day(folder)
    from cutdeck.hks_tighten import untightened
    keeps, _ = body(gold.yt)
    bleeps = gold_bleeps(folder)
    proposed = hits = n_gold = 0
    found, missed = [], []
    for media in sorted({k.media for k in keeps}):
        ks = untightened([(k.source_in, k.source_out) for k in keeps if k.media == media])
        props = proposals(words_of(folder.name[:8], media, words_dir), ks)
        want = bleeps.get(media, [])
        proposed += len(props)
        n_gold += len(want)
        hit = [p for p in props if any(p[0] - TOL <= g <= p[1] + TOL for g in want)]
        hits += len(hit)
        found += [(round(p[0], 2), p[2]) for p in hit]
        missed += [g for g in want if not any(p[0] - TOL <= g <= p[1] + TOL for p in props)]
    return {"day": folder.name[:8], "proposed": proposed, "gold": n_gold, "hits": hits,
            "precision": round(hits / proposed, 3) if proposed else None, "found": found, "missed": missed}


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
