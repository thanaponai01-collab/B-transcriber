"""HKS build plan step 2.1: word pieces for the footage of every day folder.

Each ``1. FOOTAGE/*.mp4`` goes through ``transcribe.service.transcribe`` (Engine A,
faster_whisper; the shared store caches a finished job by media sha256, so a re-run is free).
The raw word pieces of that job are written as ``[[start_s, end_s, text], ...]`` to
``<out>/<yyyymmdd>/<file stem>.words.json``. They are merged words (``ทุกครั้ง``); the ad-hoc
20261120 ``full.words.json`` holds Whisper's sub-word pieces (``ท``, ``ุ``, ``ก``), so piece
counts of the two are not comparable.

``--check`` is the step's proof: every YouTube body keep of 2 s or more (``hks_gold``) must have
a word inside it on at least ``MIN_COVERED`` of them per day, and no keep of ``LONG_KEEP`` s or
more may be without one. A kept stretch with no word is a hole in the transcript under speech
the user kept.

    python -m cutdeck.hks_words --all "G:\\Me\\Works"
    python -m cutdeck.hks_words --all "G:\\Me\\Works" --check
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cutdeck.hks_gold import HOLDOUT, body, day_folders, read_day

OUT = Path("test_projects/hks_words")
MIN_KEEP = 2.0  # s: shorter keeps can be a breath or a single syllable
MIN_COVERED = 0.97  # set before the first --check run
LONG_KEEP = 5.0  # s: a keep this long with no word is always a hole (added after a synthetic one-minute hole passed 0.97)


def footage(folder: Path) -> list[Path]:
    return sorted(p for p in (folder / "1. FOOTAGE").glob("*") if p.suffix.lower() == ".mp4")


def pieces(media: Path, config: dict) -> list[list]:
    from transcribe.db import store
    from transcribe.service import transcribe

    job = transcribe(str(media), config=config)
    conn = store.connect(store.resolve_db_path(config))
    try:
        result = store.get_engine_result(conn, job.job_id, "a")
    finally:
        conn.close()
    raw = json.loads(result.raw_words_json) if result and result.raw_words_json else []
    return [[round(w["start_ms"] / 1000, 3), round(w["end_ms"] / 1000, 3), w["text"]] for w in raw]


def summary(words: list[list]) -> dict:
    """Count, span and the longest stretch without a word (a hole in the transcript shows here)."""
    if not words:
        return {"pieces": 0}
    gaps = [b[0] - a[1] for a, b in zip(words, words[1:])]
    return {"pieces": len(words), "first": words[0][0], "last": words[-1][1], "longest_gap": round(max(gaps, default=0), 2)}


def coverage(keeps: list[tuple[str, float, float]], words: dict[str, list[list]]) -> dict:
    """keeps: (media file name, source in, source out). words: media file name -> word pieces.
    The share of keeps of MIN_KEEP s or more with at least one word overlapping them; a hole in a
    keep of LONG_KEEP s or more fails on its own."""
    long = [k for k in keeps if k[2] - k[1] >= MIN_KEEP]
    holes = [k for k in long if not any(w[0] < k[2] and w[1] > k[1] for w in words.get(k[0], []))]
    share = 1 - len(holes) / len(long) if long else None
    return {"keeps": len(long), "holes": [[m, round(a, 2), round(b, 2)] for m, a, b in holes],
            "covered": None if share is None else round(share, 4),
            "pass": share is not None and share >= MIN_COVERED and not any(b - a >= LONG_KEEP for _, a, b in holes)}


def check(folder: Path, out: Path) -> dict:
    gold = read_day(folder)
    if gold.yt is None:
        return {"day": folder.name[:8], "pass": False, "problem": "no YT cut in the gold"}
    keeps, _ = body(gold.yt)
    words = {}
    for name in {k.media for k in keeps}:
        path = out / folder.name[:8] / f"{Path(name).stem}.words.json"
        words[name] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    result = coverage([(k.media, k.source_in, k.source_out) for k in keeps], words)
    return {"day": folder.name[:8], "holdout": folder.name[:8] in HOLDOUT, **result}


def main(argv: list[str] | None = None) -> int:
    import yaml
    p = argparse.ArgumentParser(description="Word pieces for HKS day folders (step 2.1).")
    p.add_argument("folder", help="a day folder, or with --all the folder that holds them")
    p.add_argument("--all", action="store_true", help="every *โหนกระแส folder, holdout included (no tuning here)")
    p.add_argument("--out", default=str(OUT))
    p.add_argument("--check", action="store_true", help="check word coverage of the gold YT keeps; no transcribing")
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if args.check:
        folders = [d for group in day_folders(args.folder) for d in group] if args.all else [Path(args.folder)]
        results = [check(folder, Path(args.out)) for folder in sorted(folders)]
        for r in results:
            print(json.dumps(r, ensure_ascii=False), flush=True)
        return 0 if all(r["pass"] for r in results) else 1
    config = yaml.safe_load(Path("transcribe/config.yaml").read_text(encoding="utf-8"))
    folders = [d for group in day_folders(args.folder) for d in group] if args.all else [Path(args.folder)]
    for folder in sorted(folders):
        for media in footage(folder):
            out = Path(args.out) / folder.name[:8] / f"{media.stem}.words.json"
            if out.exists():
                words = json.loads(out.read_text(encoding="utf-8"))
            else:
                words = pieces(media, config)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
            print(json.dumps({"day": folder.name[:8], "file": media.name, **summary(words)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
