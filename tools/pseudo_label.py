"""Pseudo-labels from unlabelled footage: Engine A cues kept when their confidence clears a threshold.

    # how clean is each threshold? Score pipeline cues against the hand-recut manifest rows
    python -m tools.pseudo_label check --out output/pseudo_label/check.json

    # how many minutes does each threshold yield on footage?
    python -m tools.pseudo_label label --list footage.txt --out output/pseudo_label/footage.jsonl

`check` rebuilds each recut source's audio by joining its manifest slices in order, runs the real
pipeline on it (scratch DB), aligns the cue text to the human text character by character, and gives
every cue its own error count and aligned reference length. A threshold's purity is the character
error rate over the cues it keeps. The recuts were edited from pipeline output, so this purity is
optimistic. `script_conflicts` counts kept cues whose aligned human text has Latin letters and the cue
none, or the reverse: training on them sets the loanword script policy implicitly.

`label` writes one row per cue (file, start/end, text, confidence) for every file in `--list`, and
skips a file whose transcript shares a 20-character run with any gold reference.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_ROOT = Path(__file__).resolve().parents[1]
_MANIFEST = _ROOT / "transcribe" / "finetune" / "manifest.jsonl"
_GOLD = _ROOT / "transcribe" / "eval" / "goldenset"
THRESHOLDS = (0.0, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95)
_LATIN = re.compile(r"[A-Za-z]")
_SHINGLE = 20


def _config() -> dict:
    import yaml
    return yaml.safe_load((_ROOT / "transcribe" / "config.yaml").read_text(encoding="utf-8"))


def _norm(text: str, config: dict) -> str:
    from transcribe.pipeline.normalize import normalize
    return re.sub(r"\s+", "", normalize(text, config)).lower()


def _decode(path: Path, config: dict, db: Path) -> list[dict]:
    from transcribe.pipeline import run
    return run.run_file(str(path), config, db)


def score_cues(cues: list[dict], ref_text: str, config: dict) -> list[dict]:
    """Per cue: its errors and the reference characters aligned to it (one global alignment)."""
    from rapidfuzz.distance import Levenshtein
    texts = [_norm(c["text"], config) for c in cues]
    owner = [i for i, t in enumerate(texts) for _ in t]
    hyp = "".join(texts)
    ref = _norm(ref_text, config)
    errors = [0] * len(cues)
    ref_len = [0] * len(cues)
    ref_latin = [False] * len(cues)
    for tag, h0, h1, r0, r1 in Levenshtein.opcodes(hyp, ref):
        if not owner:
            break
        if tag == "equal":
            for k in range(h1 - h0):
                ref_len[owner[h0 + k]] += 1
            continue
        i = owner[min(h0, len(owner) - 1)]
        errors[i] += max(h1 - h0, r1 - r0)
        ref_len[i] += r1 - r0
        ref_latin[i] |= bool(_LATIN.search(ref[r0:r1]))
    for tag, h0, h1, r0, r1 in Levenshtein.opcodes(hyp, ref):
        if tag == "equal" and owner:
            ref_latin[owner[h0]] |= bool(_LATIN.search(ref[r0:r1]))
    return [{**c, "errors": e, "ref_chars": n,
             "script_conflict": bool(_LATIN.search(t)) != ref_latin[i] and n > 0}
            for i, (c, t, e, n) in enumerate(zip(cues, texts, errors, ref_len))]


def summarize(scored: list[dict]) -> list[dict]:
    rows = []
    total_ms = sum(c["end_ms"] - c["start_ms"] for c in scored) or 1
    for t in THRESHOLDS:
        kept = [c for c in scored if (c.get("confidence") or 0.0) >= t]
        ref_chars = sum(c["ref_chars"] for c in kept)
        rows.append({
            "threshold": t,
            "kept_cues": len(kept),
            "kept_minutes": round(sum(c["end_ms"] - c["start_ms"] for c in kept) / 60000, 2),
            "kept_share": round(sum(c["end_ms"] - c["start_ms"] for c in kept) / total_ms, 3),
            "cer": round(sum(c["errors"] for c in kept) / ref_chars, 4) if ref_chars else None,
            "script_conflicts": sum(c["script_conflict"] for c in kept),
        })
    return rows


def check(out: Path) -> None:
    import soundfile as sf
    from transcribe.db import store
    config = _config()
    rows = [json.loads(line) for line in _MANIFEST.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_source: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("origin") == "srt":
            by_source.setdefault(r["source"], []).append(r)
    scored_all = []
    with tempfile.TemporaryDirectory(prefix="pseudo_check_") as tmp:
        db = Path(tmp) / "scratch.db"
        store.init_db(db)
        for n, (source, items) in enumerate(sorted(by_source.items())):
            items.sort(key=lambda r: r["start_ms"])
            audio = np.concatenate([sf.read(str(_ROOT / r["audio"]), dtype="float32")[0] for r in items])
            wav = Path(tmp) / f"{n:02d}.wav"
            sf.write(str(wav), audio, 16000, subtype="FLOAT")
            cues = _decode(wav, config, db)
            scored = score_cues(cues, "".join(r["text"] for r in items), config)
            for c in scored:
                c["source"] = source
            scored_all.extend(scored)
            print(f"[check] {source}: {len(items)} human cues, {len(cues)} pipeline cues", flush=True)
    summary = summarize(scored_all)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "cues": scored_all}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    for row in summary:
        print(json.dumps(row))


def _gold_shingles(config: dict) -> set[str]:
    shingles: set[str] = set()
    for ref in _GOLD.glob("*.json"):
        text = _norm("".join(t["text"] for t in json.loads(ref.read_text(encoding="utf-8"))["tokens"]), config)
        shingles.update(text[i:i + _SHINGLE] for i in range(len(text) - _SHINGLE + 1))
    return shingles


def label(list_file: Path, out: Path) -> None:
    from transcribe.db import store
    config = _config()
    gold = _gold_shingles(config)
    paths = [Path(p.strip()) for p in list_file.read_text(encoding="utf-8").splitlines() if p.strip()]
    out.parent.mkdir(parents=True, exist_ok=True)
    done = {json.loads(line)["file"] for line in out.read_text(encoding="utf-8").splitlines()} if out.exists() else set()
    with tempfile.TemporaryDirectory(prefix="pseudo_label_") as tmp, out.open("a", encoding="utf-8") as fh:
        db = Path(tmp) / "scratch.db"
        store.init_db(db)
        for path in paths:
            if str(path) in done:
                continue
            cues = _decode(path, config, db)
            text = _norm("".join(c["text"] for c in cues), config)
            if any(text[i:i + _SHINGLE] in gold for i in range(len(text) - _SHINGLE + 1)):
                print(f"[label] SKIP (shares text with a gold clip): {path}", flush=True)
                fh.write(json.dumps({"file": str(path), "skipped": "gold_overlap"}, ensure_ascii=False) + "\n")
                continue
            for c in cues:
                fh.write(json.dumps({"file": str(path), "start_ms": c["start_ms"], "end_ms": c["end_ms"],
                                     "text": c["text"], "confidence": c.get("confidence")},
                                    ensure_ascii=False) + "\n")
            fh.flush()
            minutes = sum(c["end_ms"] - c["start_ms"] for c in cues) / 60000
            print(f"[label] {path}: {len(cues)} cues, {minutes:.1f} min of cue time", flush=True)


def yield_table(labels: Path) -> list[dict]:
    rows = [json.loads(line) for line in labels.read_text(encoding="utf-8").splitlines() if line.strip()]
    cues = [r for r in rows if "start_ms" in r]
    return [{"threshold": t,
             "minutes": round(sum(r["end_ms"] - r["start_ms"] for r in cues
                                  if (r["confidence"] or 0.0) >= t) / 60000, 1)}
            for t in THRESHOLDS]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--out", type=Path, default=_ROOT / "output" / "pseudo_label" / "check.json")
    lab = sub.add_parser("label")
    lab.add_argument("--list", type=Path, required=True, help="text file, one media path per line")
    lab.add_argument("--out", type=Path, default=_ROOT / "output" / "pseudo_label" / "footage.jsonl")
    y = sub.add_parser("yield")
    y.add_argument("labels", type=Path)
    args = parser.parse_args()
    if args.cmd == "check":
        check(args.out)
    elif args.cmd == "label":
        label(args.list, args.out)
    else:
        for row in yield_table(args.labels):
            print(json.dumps(row))


if __name__ == "__main__":
    main()
