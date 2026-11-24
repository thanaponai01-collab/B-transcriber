"""Frame-level timing check: how far word and cue edges land from the audio itself."""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
from pathlib import Path

import numpy as np

HOP_MS = 10
PAUSE_MS = 100
QUIET_DB = 6
LOUD_DB = 14
DECAY_MS = 300
BELOW_PEAK_DB = 30
DIGITAL_DB = -120
MATCH_MS = 300
FRAME_MS = 40


def audio_edges(y: np.ndarray, sr: int = 16000) -> tuple[list[int], list[int]]:
    import librosa
    rms = librosa.feature.rms(y=y, frame_length=sr * 25 // 1000, hop_length=sr * HOP_MS // 1000)[0]
    level = 20 * np.log10(rms + 1e-9)
    floor = np.percentile(level, 10)
    quiet, loud = level < floor + QUIET_DB, level > floor + LOUD_DB
    n = PAUSE_MS // HOP_MS
    on = [i * HOP_MS for i in range(n, len(level) - n) if loud[i] and quiet[i - n:i].all()]
    live = level[level > DIGITAL_DB]
    room = np.percentile(live, 10) if len(live) > len(level) // 10 else floor
    d = DECAY_MS // HOP_MS
    loud_room = level > room + LOUD_DB
    off: list[int] = []
    last_loud = -1
    for j in range(1, len(level) - n):
        if loud_room[j - 1]:
            last_loud = j - 1
        if last_loud < 0 or j - last_loud > d or (off and j * HOP_MS < off[-1] + PAUSE_MS):
            continue
        peak = level[max(0, last_loud - d):last_loud + 1].max()
        thr = max(room + QUIET_DB, peak - BELOW_PEAK_DB)
        if level[j - 1] >= thr and (level[j:j + n] < thr).all():
            off.append(j * HOP_MS)
    return on, off


def edge_errors(times: list[float], edges: list[int], tol_ms: int = MATCH_MS) -> list[float]:
    t = np.asarray(sorted(times), dtype=float)
    out = []
    for e in edges:
        if len(t):
            d = t[np.argmin(np.abs(t - e))] - e
            if abs(d) <= tol_ms:
                out.append(float(d))
    return out


def summary(errors: list[float]) -> dict:
    if not errors:
        return {"n": 0}
    a = sorted(abs(e) for e in errors)
    return {"n": len(errors), "median_ms": statistics.median(errors), "median_abs_ms": statistics.median(a),
            "p90_abs_ms": a[max(0, int(0.9 * len(a)) - 1)], "within_frame": sum(x <= FRAME_MS for x in a) / len(a)}


def score(y: np.ndarray, words: list[dict], cues: list[dict], sr: int = 16000) -> dict[str, list[float]]:
    on, off = audio_edges(y, sr)
    return {"word_start": edge_errors([w["start_ms"] for w in words], on),
            "word_end": edge_errors([w["end_ms"] for w in words], off),
            "cue_start": edge_errors([c["start_ms"] for c in cues], on),
            "cue_end": edge_errors([c["end_ms"] for c, n in zip(cues, cues[1:] + [None])
                                    if n is None or n["start_ms"] > c["end_ms"]], off)}


def _run(path: str, config: dict, db: Path) -> tuple[list[dict], list[dict]]:
    from transcribe.db import store
    from transcribe.pipeline import run as pipeline_run
    job_id, cues = pipeline_run.run_file_job(path, config, db)
    conn = store.connect(db)
    try:
        raw = store.get_engine_result(conn, job_id, "a").raw_words_json
    finally:
        conn.close()
    return json.loads(raw) if raw else [], cues


def _replay(manifest: Path, cache: Path, config: dict) -> dict[str, dict[str, list[float]]]:
    import copy
    import subprocess
    from types import SimpleNamespace

    import librosa
    from transcribe.pipeline import word_align
    cache.mkdir(parents=True, exist_ok=True)
    whisper_only = copy.deepcopy(config)
    whisper_only.setdefault("word_align", {})["enabled"] = False
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    total: dict[str, dict[str, list[float]]] = {}
    for clip in json.loads(manifest.read_text(encoding="utf-8"))["clips"]:
        wav, raw = cache / f"{clip['name']}.wav", cache / f"{clip['name']}.whisper.json"
        if not wav.exists():
            if not Path(clip["source"]).exists():
                print(f"{clip['name']}: source missing, skipped")
                continue
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(clip["start_s"]), "-t", "180",
                            "-i", clip["source"], "-vn", "-ac", "1", "-ar", "16000", str(wav)], check=True)
        if not raw.exists():
            words, cues = _run(str(wav), whisper_only, cache / "timing.db")
            raw.write_text(json.dumps({"words": words, "cues": cues}, ensure_ascii=False), encoding="utf-8")
        d = json.loads(raw.read_text(encoding="utf-8"))
        y, _ = librosa.load(wav, sr=16000, mono=True)
        cues = [SimpleNamespace(**c) for c in d["cues"]]
        new = word_align.align_words(d["words"], cues, y, 16000, device, config.get("word_align") or {})
        for label, w, c in (("whisper", d["words"], d["cues"]), ("aligned", new, [vars(c) for c in cues])):
            for k, v in score(y, w, c).items():
                total.setdefault(f"{clip['set']} {label}", {}).setdefault(k, []).extend(v)
    return total


def _print_all(name: str, total: dict[str, list[float]]) -> None:
    for k, v in total.items():
        s = summary(v)
        if s["n"]:
            print(f"{name} {k:10s} n={s['n']} median {s['median_ms']:+.0f} ms, |err| median {s['median_abs_ms']:.0f} ms, "
                  f"p90 {s['p90_abs_ms']:.0f} ms, within one 25 fps frame {s['within_frame']:.0%}")


def main(argv: list[str] | None = None) -> int:
    import librosa
    import yaml
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("audio", nargs="*")
    p.add_argument("--manifest", help="clip manifest for replay mode (transcribe/eval/timing_clips.json)")
    p.add_argument("--cache", default="output/timing", help="replay mode: where clips and Engine A output are kept")
    p.add_argument("--config", default=str(Path(__file__).parents[1] / "config.yaml"))
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    if args.manifest:
        for name, total in sorted(_replay(Path(args.manifest), Path(args.cache), config).items()):
            _print_all(name, total)
        return 0
    total: dict[str, list[float]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "timing.db"
        for path in args.audio:
            words, cues = _run(path, config, db)
            y, _ = librosa.load(path, sr=16000, mono=True)
            for k, v in score(y, words, cues).items():
                total.setdefault(k, []).extend(v)
                print(f"{Path(path).name:28s} {k:10s} {summary(v)}")
    _print_all("ALL", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
