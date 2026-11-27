"""Timing judge: word and cue edges against hand-marked onsets and offsets, in frames.

The judge is locked: `judge.lock` holds the sha256 of this file, the manifest and every reference
file (the lockbox's too, hashed from outside the repo). A run refuses on any mismatch and stamps
the hashes into its result, so a trial cannot move the goalposts.

Scoring, per clip, inside the clip's marked span:
- primary: each marked onset is matched to the nearest word start, each marked offset to the
  nearest word end, one-to-one, within MATCH_MS. A marked edge with no match is a miss and stays
  in the denominator (nothing is dropped). Hit within k frames: |hyp - ref| <= k frame durations
  at the clip's sequence fps (w1, w2).
- placed: the same after CutDeck snaps the time to the nearest frame (placed_w1); premiere: after
  Premiere floors an imported SRT time to the 30 fps grid (premiere_w1). The gap between w1 and
  these is the frame-rounding cost.
- cue: marked onsets matched to cue starts and offsets to cue ends (one-to-one, MATCH_MS); only
  matched pairs count (a pause inside a cue has no cue edge), so also see `cue_unmatched`."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
import time
from pathlib import Path

from transcribe.eval.judge.prepare import MANIFEST, REPO, wav_path, whisper_path

HERE = Path(__file__).parent
LOCK = HERE / "judge.lock"
REFERENCE = HERE / "reference"
RUNS = REPO / "output" / "judge_runs"
MATCH_MS = 500
KINDS = ("start", "end")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lockbox_refs(manifest: dict) -> list[Path]:
    return sorted((Path(manifest["lockbox_dir"]) / "reference").glob("*.json"))


def locked_files(manifest: dict) -> dict[str, str]:
    files = {n: HERE / n for n in ("score.py", "prepare.py", "praat.py", "causes.py")} | {"manifest.json": MANIFEST}
    files |= {f"reference/{p.name}": p for p in sorted(REFERENCE.glob("*.json"))}
    files |= {f"lockbox/{p.name}": p for p in _lockbox_refs(manifest)}
    files |= {f"audio/{c['name']}.wav": wav_path(manifest, c) for c in manifest["clips"]}
    return {k: _sha(v) for k, v in files.items()}


def check_lock(manifest: dict) -> dict[str, str]:
    now = locked_files(manifest)
    if not LOCK.exists():
        raise SystemExit("judge.lock missing: the judge is not locked yet")
    want = json.loads(LOCK.read_text(encoding="utf-8"))
    bad = sorted(k for k in set(now) | set(want) if now.get(k) != want.get(k))
    if bad:
        raise SystemExit(f"judge.lock mismatch, refusing to score: {bad}")
    return now


def frame(t_ms: float, fps: float) -> int:
    return math.floor(t_ms * fps / 1000 + 0.5)


def premiere_ms(t_ms: float) -> float:
    return math.floor(t_ms * 30 / 1000 + 1e-9) * 1000 / 30


def match(ref: list[float], hyp: list[float], window: float = MATCH_MS) -> list[float | None]:
    """For each ref edge, the hypothesis time matched to it (nearest first, one-to-one), or None."""
    pairs = sorted((abs(h - r), i, j) for i, r in enumerate(ref) for j, h in enumerate(hyp) if abs(h - r) <= window)
    out: list[float | None] = [None] * len(ref)
    used: set[int] = set()
    for _, i, j in pairs:
        if out[i] is None and j not in used:
            out[i] = hyp[j]
            used.add(j)
    return out


def edge_rows(ref: dict, words: list[dict], cues: list[dict], fps: float) -> list[dict]:
    """One row per marked edge: its kind, ref time, matched word edge and cue edge (or None)."""
    a, b = ref["span_ms"]
    rows = []
    for kind, tier, key in (("start", "onset", "start_ms"), ("end", "offset", "end_ms")):
        marks = sorted(ref[tier])
        hyp_w = [w[key] for w in words if a - MATCH_MS <= w[key] <= b + MATCH_MS]
        hyp_c = [c[key] for c in cues if a - MATCH_MS <= c[key] <= b + MATCH_MS]
        for r, hw, hc in zip(marks, match(marks, hyp_w), match(marks, hyp_c)):
            rows.append({"clip": ref["clip"], "kind": kind, "ref": r, "word": hw, "cue": hc, "fps": fps})
    return rows


def _hit(r: float, h: float | None, fps: float, k: int, how: str = "raw") -> bool:
    if h is None:
        return False
    if how == "placed":
        h = frame(h, fps) * 1000 / fps
    elif how == "premiere":
        h = premiere_ms(h)
    return abs(h - r) <= k * 1000 / fps + 1e-6


def summarize(rows: list[dict]) -> dict:
    out: dict = {"n": len(rows)}
    for kind in KINDS + ("all",):
        rs = [r for r in rows if kind == "all" or r["kind"] == kind]
        if not rs:
            continue
        n = len(rs)
        cue = [r for r in rs if r["cue"] is not None]
        out[kind] = {
            "n": n,
            "missed": sum(r["word"] is None for r in rs),
            "w1": sum(_hit(r["ref"], r["word"], r["fps"], 1) for r in rs) / n,
            "w2": sum(_hit(r["ref"], r["word"], r["fps"], 2) for r in rs) / n,
            "placed_w1": sum(_hit(r["ref"], r["word"], r["fps"], 1, "placed") for r in rs) / n,
            "premiere_w1": sum(_hit(r["ref"], r["word"], r["fps"], 1, "premiere") for r in rs) / n,
            "median_ms": _median([r["word"] - r["ref"] for r in rs if r["word"] is not None]),
            "cue_n": len(cue),
            "cue_w1": sum(_hit(r["ref"], r["cue"], r["fps"], 1) for r in cue) / len(cue) if cue else None,
            "cue_w2": sum(_hit(r["ref"], r["cue"], r["fps"], 2) for r in cue) / len(cue) if cue else None,
        }
    return out


def _median(xs: list[float]) -> float | None:
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


def paired_delta(a: list[dict], b: list[dict], k: int = 1, iters: int = 2000, seed: int = 0) -> dict:
    """Run b minus run a on the same marked edges: change in the within-k rate with a 95% bootstrap
    CI that resamples whole clips (edges in one clip are not independent), and the edges that
    moved by at least one frame either way."""
    key = lambda r: (r["clip"], r["kind"], r["ref"])
    bm = {key(r): r for r in b}
    pairs = [(r, bm[key(r)]) for r in a if key(r) in bm]
    per_clip: dict[str, list[int]] = {}
    for x, y in pairs:
        per_clip.setdefault(x["clip"], []).append(int(_hit(y["ref"], y["word"], y["fps"], k))
                                                  - int(_hit(x["ref"], x["word"], x["fps"], k)))
    clips = sorted(per_clip)
    rng = random.Random(seed)
    boots = []
    for _ in range(iters if clips else 0):
        pick = [per_clip[rng.choice(clips)] for _ in clips]
        n = sum(len(v) for v in pick)
        boots.append(sum(sum(v) for v in pick) / n if n else 0.0)
    boots = sorted(boots) or [0.0]

    def err(r):
        return 1e9 if r["word"] is None else abs(r["word"] - r["ref"]) * r["fps"] / 1000
    better = sum(err(y) <= err(x) - 1 for x, y in pairs)
    worse = sum(err(y) >= err(x) + 1 for x, y in pairs)
    total = sum(sum(v) for v in per_clip.values())
    return {"n": len(pairs), "clips": len(clips), "delta": total / len(pairs) if pairs else 0.0,
            "ci95": [boots[int(0.025 * len(boots))], boots[min(len(boots) - 1, int(0.975 * len(boots)))]],
            "edges_better_1f": better, "edges_worse_1f": worse}


def replay(clip: dict, manifest: dict, config: dict, tag: str = "") -> tuple[list[dict], list[dict], dict]:
    """word_align (as the code under test does it) on the clip's cached Engine A output."""
    from types import SimpleNamespace

    import librosa
    import torch
    from transcribe.pipeline import word_align
    d = json.loads(whisper_path(manifest, clip, tag).read_text(encoding="utf-8"))
    cfg = config.get("word_align") or {}
    if not cfg.get("enabled", True):
        return d["words"], d["cues"], {}
    y, _ = librosa.load(wav_path(manifest, clip), sr=16000, mono=True)
    cues = [SimpleNamespace(**c) for c in d["cues"]]
    t = time.perf_counter()
    words = word_align.align_words(d["words"], cues, y, 16000, "cuda" if torch.cuda.is_available() else "cpu", cfg)
    return words, [vars(c) for c in cues], {"word_align_s": time.perf_counter() - t, "text": [w["text"] for w in words]}


def load_refs(manifest: dict, split: str) -> dict[str, dict]:
    paths = _lockbox_refs(manifest) if split == "lockbox" else sorted(REFERENCE.glob("*.json"))
    refs = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in paths}
    names = {c["name"] for c in manifest["clips"] if c["split"] == split}
    return {k: v for k, v in refs.items() if k in names}


def run(split: str, config: dict, label: str, tag: str = "", milestone: bool = False) -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    hashes = check_lock(manifest)
    if split == "lockbox":
        stamp = Path(manifest["lockbox_dir"]) / "milestone.jsonl"
        if not milestone or stamp.exists():
            raise SystemExit("the lockbox is scored once, at the milestone (--milestone), and it has "
                             + ("already been scored" if stamp.exists() else "not been asked for"))
    refs = load_refs(manifest, split)
    clips = {c["name"]: c for c in manifest["clips"]}
    rows: list[dict] = []
    texts: dict[str, list[str]] = {}
    for name, ref in sorted(refs.items()):
        words, cues, info = replay(clips[name], manifest, config, tag)
        texts[name] = [w["text"] for w in words]
        rows += edge_rows(ref, words, cues, clips[name]["fps"])
    result = {"label": label, "split": split, "tag": tag, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
              "hashes": hashes, "summary": summarize(rows),
              "per_clip": {n: summarize([r for r in rows if r["clip"] == n]) for n in refs},
              "text_sha": hashlib.sha256(json.dumps(texts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()}
    if split == "lockbox":
        stamp.write_text(json.dumps({k: result[k] for k in ("label", "time", "summary")}) + "\n", encoding="utf-8")
        return result
    result["rows"] = rows
    return result


GOLD = REPO / "transcribe" / "eval" / "goldenset"
FINISHED = {"gold_Short1": "Short1.json", "gold_Short2": "Short2.json", "gold_Short3": "Short3.json",
            "gold_singapore": "yt t1 singapore first min.json"}


def finished(config: dict) -> dict:
    """The user's own finished caption edges (the gold set's hand-recut cues) scored against the
    marks, beside the pipeline's cue edges on the same audio. Captions that follow reading rules
    (lead-in, minimum duration, closed gaps) score low here by design."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    check_lock(manifest)
    refs = load_refs(manifest, "heldout")
    clips = {c["name"]: c for c in manifest["clips"]}
    out = {}
    for name, gold in FINISHED.items():
        if name not in refs:
            continue
        user = json.loads((GOLD / gold).read_text(encoding="utf-8"))["tokens"]
        _, cues, _ = replay(clips[name], manifest, config)
        fps = clips[name]["fps"]
        out[name] = {"user": summarize(edge_rows(refs[name], user, user, fps)),
                     "pipeline_cues": summarize(edge_rows(refs[name], cues, cues, fps))}
    return out


def main(argv: list[str] | None = None) -> int:
    import yaml
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--split", choices=["tune", "heldout", "lockbox"], required=True)
    r.add_argument("--config", default=str(REPO / "transcribe" / "config.yaml"))
    r.add_argument("--label", required=True)
    r.add_argument("--tag", default="", help="Engine A cache variant")
    r.add_argument("--milestone", action="store_true")
    c = sub.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    sub.add_parser("lock")
    f = sub.add_parser("finished")
    f.add_argument("--config", default=str(REPO / "transcribe" / "config.yaml"))
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if args.cmd == "lock":
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        LOCK.write_text(json.dumps(locked_files(manifest), indent=1) + "\n", encoding="utf-8")
        print(f"locked {len(locked_files(manifest))} files")
        return 0
    if args.cmd == "compare":
        a = json.loads(Path(args.a).read_text(encoding="utf-8"))
        b = json.loads(Path(args.b).read_text(encoding="utf-8"))
        if a["hashes"] != b["hashes"]:
            raise SystemExit("runs were scored by different judges")
        print(json.dumps({f"w{k}": paired_delta(a["rows"], b["rows"], k) for k in (1, 2)}
                         | {"same_text": a["text_sha"] == b["text_sha"]}, indent=1))
        return 0
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    if args.cmd == "finished":
        print(json.dumps(finished(config), indent=1))
        return 0
    result = run(args.split, config, args.label, args.tag, args.milestone)
    if args.split != "lockbox":
        RUNS.mkdir(parents=True, exist_ok=True)
        out = RUNS / f"{time.strftime('%Y%m%d-%H%M%S')}-{args.split}-{args.label}.json"
        out.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        print(f"result: {out}")
    print(json.dumps({"summary": result["summary"], "text_sha": result["text_sha"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
