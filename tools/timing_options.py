"""Edge-timing options on the locked judge, through the same scorer (score.edge_rows / summarize),
and the error bars `cutdeck.timeline_transcript` puts on every word edge.

Options, each from one cached Engine A output per clip, scored as the timeline tool shows words
(pieces merged into Thai words, `transcribe.words.words_from_pieces`):
  whisper              Engine A's own times (a transcript stored before word_align)
  whisper+tighten      the tool before this change, on such a transcript
  ctc:<model>+tighten  the tool before this change, on a transcript word_align made
  ctc:<model>          word_align as the pipeline runs it (CTC + start/end snaps, config knobs)
  energy               no CTC: the configured start/end snaps on Engine A's times
`pieces:ctc:sakares` is the judge's own view (word_align pieces), for comparison with TRIALS.md.

    python tools/timing_options.py run    # table -> output/judge_runs/options.json
    python tools/timing_options.py fit    # bars on tune -> cutdeck/edge_bars.json; heldout coverage
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from transcribe.eval.judge import score  # noqa: E402
from transcribe.eval.judge.prepare import MANIFEST, REPO, wav_path, whisper_path  # noqa: E402

MODELS_DIR = Path("E:/Me/5.Claude/Transcriber_v2/models")  # gitignored checkpoints live in the main checkout
MODELS = {"sakares": "wav2vec2-th-ctc.pt", "airesearch": "wav2vec2-th-ctc-airesearch.pt"}
CURRENT = "ctc:sakares"
MS_THRESHOLDS = (20, 40, 80)
OUT = score.RUNS / "options.json"
COVER = 0.9
MIN_GROUP = 8


def _audio(manifest, clip):
    import librosa
    y, _ = librosa.load(wav_path(manifest, clip), sr=16000, mono=True)
    return y


def tool_view(pieces: list[dict], levels, ctc: bool) -> list[dict]:
    """Words as `timeline_transcript.source_words(bars=True)` makes them from stored pieces."""
    from cutdeck import timeline_transcript as tt
    from transcribe.words import words_from_pieces
    words = [tt.SourceWord(w.text, w.start_ms, w.end_ms, 0) for w in
             words_from_pieces([(p["text"], int(p["start_ms"]), int(p["end_ms"]), p.get("confidence")) for p in pieces])]
    if ctc:
        words = tt.placed_words(words, pieces)
    else:
        words = [tt.replace(w, start_by="tightened", end_by="tightened") for w in tt.tighten(words, levels)]
    out = []
    for w in words:
        collapsed = w.end_ms - w.start_ms < tt.COLLAPSED_MS
        out.append({"text": w.text, "start_ms": w.start_ms, "end_ms": w.end_ms,
                    "start_by": "collapsed" if collapsed else w.start_by, "end_by": "collapsed" if collapsed else w.end_by,
                    "start_step": tt.edge_step_db(levels, w.start_ms, "start"), "end_step": tt.edge_step_db(levels, w.end_ms, "end")})
    return out


def clip_options(clip, manifest, config) -> dict:
    """{option: (words, cues)} for one clip."""
    import torch
    from cutdeck import timeline_transcript as tt
    from transcribe.pipeline import word_align as wa
    d = json.loads(whisper_path(manifest, clip).read_text(encoding="utf-8"))
    y = _audio(manifest, clip)
    tool_levels = tt.level_db(y, 16000)
    cfg = config.get("word_align") or {}
    lev = wa.levels_db(y, 16000)
    sk, ek = dict(cfg.get("start_snap") or {}), dict(cfg.get("end_snap") or {})
    snap = lambda s, prev: wa.snap_to_sound(s, prev, lev, **sk)  # noqa: E731
    snap_end = lambda s, a: wa.snap_end_to_sound(s, a, lev, **ek)  # noqa: E731
    dur, pad = len(y) * 1000 // 16000, int(cfg.get("pad_ms", 400))
    whisper = [dict(w) for w in d["words"]]
    out = {"whisper": (tool_view(whisper, tool_levels, True), d["cues"]),
           "whisper+tighten": (tool_view(whisper, tool_levels, False), d["cues"])}
    none = lambda lo, hi, texts: [None] * len(texts)  # noqa: E731
    energy = wa.retime_words(whisper, [SimpleNamespace(**c) for c in d["cues"]], none, lambda t: True, pad, dur, snap, snap_end)
    out["energy"] = (tool_view(energy, tool_levels, True), d["cues"])
    device = "cuda" if torch.cuda.is_available() else "cpu"
    for name, file in MODELS.items():
        cues = [SimpleNamespace(**c) for c in d["cues"]]
        new = wa.align_words(whisper, cues, y, 16000, device, {**cfg, "model": str(MODELS_DIR / file)})
        cue_dicts = [vars(c) for c in cues]
        out[f"ctc:{name}"] = (tool_view(new, tool_levels, True), cue_dicts)
        out[f"ctc:{name}+tighten"] = (tool_view(new, tool_levels, False), cue_dicts)
        if name == "sakares":
            out["pieces:ctc:sakares"] = (new, cue_dicts)
    return out


def scored_rows(ref, words, cues, fps) -> list[dict]:
    """score.edge_rows, each matched row carrying its word edge's placement and energy step."""
    rows = score.edge_rows(ref, words, cues, fps)
    feats = {(w["start_ms"], "start"): (w.get("start_by"), w.get("start_step")) for w in words}
    feats |= {(w["end_ms"], "end"): (w.get("end_by"), w.get("end_step")) for w in words}
    for r in rows:
        if r["word"] is not None:
            r["how"], r["step"] = feats.get((r["word"], r["kind"]), (None, None))
    return rows


def ms_summary(rows):
    errs = sorted(abs(r["word"] - r["ref"]) for r in rows if r["word"] is not None)
    n = len(rows)
    out = {f"within_{t}ms": sum(e <= t for e in errs) / n for t in MS_THRESHOLDS} if n else {}
    if errs:
        out["abs_median_ms"] = errs[len(errs) // 2]
        out["abs_p90_ms"] = errs[int(0.9 * (len(errs) - 1))]
    return out


def collect(config: dict, splits=("tune", "heldout")) -> tuple[dict, dict]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    hashes = score.check_lock(manifest)
    clips = {c["name"]: c for c in manifest["clips"]}
    rows: dict = {}
    for split in splits:
        for name, ref in sorted(score.load_refs(manifest, split).items()):
            for opt, (words, cues) in clip_options(clips[name], manifest, config).items():
                rows.setdefault(split, {}).setdefault(opt, []).extend(scored_rows(ref, words, cues, clips[name]["fps"]))
            print(split, name, "done", file=sys.stderr)
    return rows, hashes


def table(rows: dict) -> dict:
    out = {}
    for split, by in rows.items():
        base = by[CURRENT]
        out[split] = {opt: {"summary": score.summarize(rs), "ms": ms_summary(rs),
                            "vs_current": None if opt == CURRENT else score.paired_delta(base, rs)}
                      for opt, rs in by.items()}
    return out


def _err(r):
    return abs(r["word"] - r["ref"])


def _q(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(math.ceil(q * len(xs)) - 1))] if xs else None


def _auroc(scores, good):
    pos = [s for s, g in zip(scores, good) if g]
    neg = [s for s, g in zip(scores, good) if not g]
    if not pos or not neg:
        return None
    return sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg))


def fit_bars(tune: list[dict]) -> dict:
    """Bars per (kind, how, energy-step band), else per (kind, how), else one: each the COVER
    quantile of |error| over at least MIN_GROUP matched tune edges."""
    rows = [r for r in tune if r["word"] is not None and r.get("how")]
    steps = sorted(r["step"] for r in rows if r["step"] is not None)
    cuts = [steps[len(steps) // 3], steps[2 * len(steps) // 3]]
    groups: dict[str, list[float]] = {}
    for r in rows:
        groups.setdefault(f"{r['kind']}|{r['how']}", []).append(_err(r))
        if r["step"] is not None:
            groups.setdefault(f"{r['kind']}|{r['how']}|{sum(r['step'] > c for c in cuts)}", []).append(_err(r))
    bars = {g: int(round(_q(v, COVER))) for g, v in sorted(groups.items()) if len(v) >= MIN_GROUP}
    return {"cover": COVER, "step_cuts": [round(c, 2) for c in cuts], "fallback": int(round(_q([_err(r) for r in rows], COVER))),
            "bars": bars, "tune_n": {g: len(v) for g, v in sorted(groups.items())}}


def check_bars(fit: dict, held: list[dict]) -> dict:
    """Heldout: share of matched edges inside their bar, overall and per placement."""
    from cutdeck import timeline_transcript as tt
    tt._bars = fit
    rows = [r for r in held if r["word"] is not None and r.get("how")]
    inside, width, by = [], [], {}
    for r in rows:
        b = tt.edge_bar(r["kind"], r["how"], r["step"])
        if b is None:
            continue
        ok = _err(r) <= b
        inside.append(ok)
        width.append(b)
        k = f"{r['kind']}|{r['how']}"
        by.setdefault(k, [0, 0])
        by[k][0] += ok
        by[k][1] += 1
    tt._bars = None
    return {"coverage": sum(inside) / len(inside), "mean_bar_ms": sum(width) / len(width), "n": len(inside),
            "by_placement": {k: {"inside": a, "n": n} for k, (a, n) in sorted(by.items())}}


def calibration(rows: dict) -> dict:
    """The bar fitted on tune (winner + the stale-transcript path), checked on heldout, beside
    one constant bar and the AUROC of each signal for "within one frame"."""
    tune = rows["tune"][CURRENT] + rows["tune"]["whisper+tighten"]
    fit = fit_bars(tune)
    held_w, held_t = rows["heldout"][CURRENT], rows["heldout"]["whisper+tighten"]
    one = {"cover": COVER, "step_cuts": [], "fallback": fit["fallback"], "bars": {}}
    m = [r for r in held_w if r["word"] is not None and r.get("how")]
    good = [_err(r) <= 1000 / r["fps"] for r in m]
    return {"fit": fit,
            "heldout_winner": check_bars(fit, held_w), "heldout_stale": check_bars(fit, held_t),
            "heldout_winner_one_bar": check_bars(one, held_w),
            "auroc_energy_step": _auroc([r["step"] if r["step"] is not None else 0 for r in m], good),
            "auroc_placed_by_snap": _auroc([r["how"] == "snap" for r in m], good)}


def main(argv=None) -> int:
    import yaml
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("cmd", choices=["run", "fit"])
    p.add_argument("--config", default=str(REPO / "transcribe" / "config.yaml"))
    args = p.parse_args(argv)
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    rows, hashes = collect(config)
    res = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "hashes": hashes, "table": table(rows), "calibration": calibration(rows)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    OUT.with_suffix(".rows.json").write_text(json.dumps(rows, default=float), encoding="utf-8")
    if args.cmd == "fit":
        from cutdeck.timeline_transcript import EDGE_BARS
        fit = res["calibration"]["fit"]
        EDGE_BARS.write_text(json.dumps({
            "about": "Word-edge error bars: the 90th percentile of |edge - marked sound edge| per placement and "
                     "energy-step band, fitted on the timing judge's tune split; written by "
                     "python tools/timing_options.py fit",
            "reference": "provisional agent marks (judge.lock); refit when the Praat marks are collected",
            "fitted": res["time"], "judge_lock": hashes.get("score.py"),
            "heldout_coverage": res["calibration"]["heldout_winner"]["coverage"], **fit}, indent=1), encoding="utf-8")
    for split, opts in res["table"].items():
        for opt, v in opts.items():
            s, ms, vc = v["summary"], v["ms"], v["vs_current"]
            print(f"{split:8} {opt:22} w1 {s['all']['w1']:.3f} (start {s['start']['w1']:.3f} end {s['end']['w1']:.3f}) "
                  f"w2 {s['all']['w2']:.3f} missed {s['all']['missed']:3} "
                  f"20ms {ms['within_20ms']:.3f} 40ms {ms['within_40ms']:.3f} 80ms {ms['within_80ms']:.3f} "
                  f"|e| med {ms['abs_median_ms']:.0f} p90 {ms['abs_p90_ms']:.0f}"
                  + (f"  d {vc['delta']:+.3f} [{vc['ci95'][0]:+.3f},{vc['ci95'][1]:+.3f}] {vc['edges_better_1f']}/{vc['edges_worse_1f']}" if vc else ""))
    print(json.dumps({k: v for k, v in res["calibration"].items() if k != "fit"}, indent=1, default=str))
    print(json.dumps(res["calibration"]["fit"]["bars"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
