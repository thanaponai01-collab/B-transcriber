"""GPU-free segmentation replay: score the cue splitter against the user's Premiere recuts.

python -m tools.replay_segmentation                       # baseline = config.yaml
python -m tools.replay_segmentation --grid target_chars=30,36,42 --grid max_close_gap_ms=200,400
python -m tools.replay_segmentation --only "CFD 95" --verbose

For every hand-recut SRT in CLIPS it loads the cached Engine A raw words from
transcriber.db (the latest job whose media path matches), replays them through
split_cues + conform_cues exactly as production does, and scores cue starts
against the recut with the same matcher and tolerance as
metrics.cue_boundary_error_rate. Recognition text is checked: a candidate whose
whitespace-stripped text differs from the baseline's is flagged TEXT CHANGED.
Replay stops at conform_cues: normalization and silence filtering are skipped.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sqlite3
import statistics
import sys
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from transcribe.cues import CuePolicy, split_cues
from transcribe.eval.metrics import _match_points, boundary_f1_error
from transcribe.pipeline.align_force import conform_cues
from transcribe.subtitles import read_subtitles
from transcribe.thai.atoms import default_lexicon

ROOT = Path(__file__).resolve().parent.parent
WORKS = Path("F:/Me/Works")
TOL_MS = 300  # same as config boundary_tol_ms


@dataclass(frozen=True)
class Clip:
    label: str
    srt: str          # relative to WORKS
    media: str        # forward-slash substring of the job's media path


def _cfd(n, folder, sub, stem, ref):
    return Clip(f"CFD {n} {stem}", f"{folder}/5. EXPORTS/{sub}/{ref}", f"{folder}/5. EXPORTS/{sub}/{stem}.mp3")


_P92, _P93 = "20260807 - CFD 92", "20260820 - CFD 93"
_PUD, _HON = "20260805 - พุธทอล์คพุธโทร 224", "20260807 - โหน(หลัง)กระแส 155"
CLIPS = [
    *[_cfd(92, _P92, "short", f"Short{i}", f"mine-Short{i}.srt") for i in range(1, 5)],
    *[_cfd(93, _P93, "audio", f"Short{i}", f"mineShort{i}.srt") for i in range(1, 5)],
    _cfd(95, "20260917 - CFD 95", "audio", "shorts", "shorts_mine.srt"),
    Clip("hon trim 3 mins", f"{_HON}/5. EXPORTS/hon trim 3 mins mine.srt", f"{_HON}/5. EXPORTS/Audio test.mp3"),
    Clip("pud trim down", f"{_PUD}/5. EXPORTS/mine test trim down.srt", f"{_PUD}/5. EXPORTS/"),
    Clip("pud trim down2", f"{_PUD}/5. EXPORTS/mine test trim down2.srt", f"{_PUD}/5. EXPORTS/"),
    Clip("Bangkok SOUND FINAL", "20260625 - Bangkok Festivals - CT6/5. EXPORTS/audio/SOUND FINAL mine.srt",
         "20260625 - Bangkok Festivals - CT6/5. EXPORTS/SOUND FINAL.mp3"),
]

# grid / --set key -> where it lives
_POLICY_KEYS = {"gap_ms": "gap_ms", "max_ms": "target_ms", "target_chars": "target_chars",
                "space_min_chars": "space_min_chars", "space_min_ms": "space_min_ms",
                "algorithm": "algorithm"}
_ALL_KEYS = sorted([*_POLICY_KEYS, "max_close_gap_ms"])


def load_config() -> dict:
    return yaml.safe_load((ROOT / "transcribe" / "config.yaml").read_text(encoding="utf-8"))


def baseline_settings(config: dict) -> dict:
    fw = config["engines"]["faster_whisper"]
    return {"gap_ms": fw["cue_gap_ms"], "max_ms": fw["cue_max_ms"], "target_chars": fw["cue_target_chars"],
            "space_min_chars": fw["cue_space_min_chars"], "space_min_ms": fw["cue_space_min_ms"],
            "algorithm": fw.get("cue_split_algorithm", "greedy"),
            "max_close_gap_ms": int(config.get("cue_max_close_gap_ms", 200))}


def find_words(conn: sqlite3.Connection, media_substr: str) -> tuple[int, list[tuple]] | None:
    """Latest job whose media path contains media_substr and which cached raw words."""
    rows = conn.execute(
        "SELECT j.id, m.path, e.raw_words_json FROM job j JOIN media m ON m.id = j.media_id "
        "JOIN engine_result e ON e.job_id = j.id AND e.engine_slot = 'a' "
        "WHERE e.raw_words_json IS NOT NULL ORDER BY j.id DESC").fetchall()
    for job_id, path, raw in rows:
        if media_substr in path.replace("\\", "/"):
            return job_id, [(w["text"], w["start_ms"], w["end_ms"], w["confidence"]) for w in json.loads(raw)]
    return None


@dataclass
class _Tok:
    text: str
    start_ms: int
    end_ms: int


def replay(words, settings: dict, config: dict, duration_ms: int | None = None) -> list[dict]:
    """Production splitter + conform on cached words -> cue dicts (text/start_ms/end_ms)."""
    policy = CuePolicy(**{_POLICY_KEYS[k]: settings[k] for k in _POLICY_KEYS},
                       lexicon=default_lexicon(config))
    toks = [_Tok(t, s, e) for t, s, e, _ in split_cues(words, policy)]
    conform_cues(toks, max_close_gap_ms=settings["max_close_gap_ms"], duration_ms=duration_ms)
    return [{"text": t.text, "start_ms": t.start_ms, "end_ms": t.end_ms} for t in toks]


def _pct(values, q):
    if not values:
        return 0
    s = sorted(values)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def score(ref: list[dict], hyp: list[dict]) -> dict:
    # Some recuts cover only an excerpt (e.g. the first 3 minutes) of a longer job.
    hyp = [c for c in hyp if c["start_ms"] <= ref[-1]["end_ms"] + TOL_MS]
    matched = _match_points([float(c["start_ms"]) for c in ref], [float(c["start_ms"]) for c in hyp], TOL_MS)
    dur = [c["end_ms"] - c["start_ms"] for c in hyp]
    chars = [len(c["text"].replace(" ", "")) for c in hyp]
    gaps = sum(1 for a, b in zip(hyp, hyp[1:]) if b["start_ms"] > a["end_ms"])
    return {"ref": len(ref), "hyp": len(hyp), "matched": matched,
            "cue_ber": boundary_f1_error(matched, len(ref), len(hyp)), "delta": len(hyp) - len(ref),
            "gaps": gaps, "dur": dur, "chars": chars}


def text_key(cues: list[dict]) -> str:
    return "".join("".join(c["text"].split()) for c in cues)


LONG_REF_CUES = 500  # full-episode recuts; they dominate a micro-F1 pool, so also pool without them


def pool_of(scores) -> dict:
    scores = list(scores)
    pool = {k: sum(p[k] for p in scores) for k in ("ref", "hyp", "matched", "delta", "gaps")}
    pool["cue_ber"] = boundary_f1_error(pool["matched"], pool["ref"], pool["hyp"])
    pool["macro_ber"] = statistics.fmean(p["cue_ber"] for p in scores) if scores else 0.0
    pool["dur"] = [d for p in scores for d in p["dur"]]
    pool["chars"] = [c for p in scores for c in p["chars"]]
    return pool


def run_setting(clips_data, settings: dict, config: dict, base_text: dict | None) -> dict:
    per, text_changed = {}, []
    for label, ref, words, dur_ms in clips_data:
        hyp = replay(words, settings, config, dur_ms)
        per[label] = score(ref, hyp)
        if base_text is not None and text_key(hyp) != base_text[label]:
            text_changed.append(label)
    pools = {"ALL": pool_of(per.values()),
             "SHORT": pool_of(p for p in per.values() if p["ref"] <= LONG_REF_CUES)}
    return {"per": per, "pools": pools, "pool": pools["ALL"], "text_changed": text_changed}


def _row(name, s):
    d, c = s["dur"], s["chars"]
    return (f"{name:<22} ref {s['ref']:>4} hyp {s['hyp']:>4} d{s['delta']:>+4} "
            f"BER {s['cue_ber']:.4f}  gaps {s['gaps']:>3}  "
            f"dur p50/p90/max {_pct(d, .5)}/{_pct(d, .9)}/{max(d, default=0)}  "
            f"chars p50/p90/max {_pct(c, .5)}/{_pct(c, .9)}/{max(c, default=0)}")


def load_clips(only: str | None):
    conn = sqlite3.connect(ROOT / "transcriber.db")
    data, skipped = [], []
    for clip in CLIPS:
        if only and only.lower() not in clip.label.lower():
            continue
        srt = WORKS / clip.srt
        found = find_words(conn, clip.media)
        if not srt.exists() or found is None:
            skipped.append((clip.label, "no SRT" if not srt.exists() else "no cached job"))
            continue
        ref = read_subtitles(srt.read_text(encoding="utf-8-sig"))
        job_id, words = found
        data.append((f"{clip.label} (j{job_id})", ref, words, None))
    return data, skipped


def parse_grid(items: list[str]) -> dict[str, list]:
    grid = {}
    for item in items:
        key, _, vals = item.partition("=")
        if key not in _ALL_KEYS:
            sys.exit(f"unknown key {key!r}; choose from {_ALL_KEYS}")
        grid[key] = [v if key == "algorithm" else int(v) for v in vals.split(",")]
    return grid


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grid", action="append", default=[], metavar="KEY=V1,V2", help=f"keys: {_ALL_KEYS}")
    ap.add_argument("--only", help="substring of clip label")
    ap.add_argument("--verbose", action="store_true", help="per-clip rows for every setting")
    ap.add_argument("--json", type=Path, help="write all results here")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    config = load_config()
    base = baseline_settings(config)
    data, skipped = load_clips(args.only)
    for label, why in skipped:
        print(f"SKIPPED {label}: {why}")
    if not data:
        sys.exit("no clips to replay")

    base_text = {label: text_key(replay(words, base, config, dur)) for label, _, words, dur in data}
    baseline = run_setting(data, base, config, base_text)
    print(f"baseline settings: {base}\n")
    for label, s in baseline["per"].items():
        print(_row(label, s))
    for name, pool in baseline["pools"].items():
        print(_row(f"POOLED {name}", pool) + f"  macroBER {pool['macro_ber']:.4f}")

    grid = parse_grid(args.grid)
    results = [{"settings": base, "pools": baseline["pools"], "text_changed": baseline["text_changed"]}]
    if grid:
        print(f"\n{'candidate':<60} pooledBER  d(base)  wins/ties/losses  cues  gaps  text")
        keys = list(grid)
        for combo in itertools.product(*grid.values()):
            cand = {**base, **dict(zip(keys, combo))}
            if cand == base:
                continue
            res = run_setting(data, cand, config, base_text)
            wins = sum(res["per"][k]["cue_ber"] < baseline["per"][k]["cue_ber"] - 1e-9 for k in res["per"])
            loss = sum(res["per"][k]["cue_ber"] > baseline["per"][k]["cue_ber"] + 1e-9 for k in res["per"])
            p, sp = res["pools"]["ALL"], res["pools"]["SHORT"]
            bp, bs = baseline["pools"]["ALL"], baseline["pools"]["SHORT"]
            print(f"{dict(zip(keys, combo))!s:<52} {p['cue_ber']:.4f} {p['cue_ber'] - bp['cue_ber']:+.4f}  "
                  f"{sp['cue_ber']:.4f}  {sp['cue_ber'] - bs['cue_ber']:+.4f}  {sp['macro_ber']:.4f}        "
                  f"{wins}/{len(res['per']) - wins - loss}/{loss}  {p['hyp']:>4}  {p['gaps']:>3}  "
                  f"{'TEXT CHANGED ' + str(res['text_changed']) if res['text_changed'] else 'same'}")
            if args.verbose:
                for label, s in res["per"].items():
                    print("   " + _row(label, s))
            results.append({"settings": cand, "pools": res["pools"], "text_changed": res["text_changed"],
                            "per": {k: {kk: vv for kk, vv in v.items() if kk not in ("dur", "chars")}
                                    for k, v in res["per"].items()}})
    if args.json:
        args.json.write_text(json.dumps(results, ensure_ascii=False, indent=1, default=list), encoding="utf-8")


if __name__ == "__main__":
    main()
