"""Frame-level timing check: how far word and cue edges land from the audio itself.

The gated cue metric matches cue starts within ±300 ms (about 9 frames), so it cannot see a
change of a frame or two. This check needs no reference text. It finds the moments speech
starts after a pause and stops before one in the waveform, then measures the nearest engine
word start (or end) to each, one match per audio edge.

Descriptive, not gated. Use clean speech (a raw mic or studio track): music under the voice
hides the pauses. A clip with few pauses gives few edges, and the report says how many.

    python -m transcribe.eval.timing clip1.wav clip2.wav [--config transcribe/config.yaml]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
from pathlib import Path

import numpy as np

HOP_MS = 10
PAUSE_MS = 100        # quiet this long before an onset (after an offset) makes it an edge
QUIET_DB = 6          # above the clip's noise floor (10th percentile of 10 ms frame levels)
LOUD_DB = 14
MATCH_MS = 300        # an edge with no engine time this close is not counted
FRAME_MS = 40         # one frame at 25 fps, for the "within a frame" share


def audio_edges(y: np.ndarray, sr: int = 16000) -> tuple[list[int], list[int]]:
    """(onsets, offsets) in ms: a loud 10 ms frame right after (before) PAUSE_MS of quiet."""
    import librosa
    rms = librosa.feature.rms(y=y, frame_length=sr * 25 // 1000, hop_length=sr * HOP_MS // 1000)[0]
    level = 20 * np.log10(rms + 1e-9)
    floor = np.percentile(level, 10)
    quiet, loud = level < floor + QUIET_DB, level > floor + LOUD_DB
    n = PAUSE_MS // HOP_MS
    on = [i * HOP_MS for i in range(n, len(level) - n) if loud[i] and quiet[i - n:i].all()]
    off = [(i + 1) * HOP_MS for i in range(n, len(level) - n) if loud[i] and quiet[i + 1:i + 1 + n].all()]
    return on, off


def edge_errors(times: list[float], edges: list[int], tol_ms: int = MATCH_MS) -> list[float]:
    """Signed error (time - edge) of the nearest time to each edge within ``tol_ms``."""
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
            "cue_start": edge_errors([c["start_ms"] for c in cues], on)}


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


def main(argv: list[str] | None = None) -> int:
    import librosa
    import yaml
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("audio", nargs="+")
    p.add_argument("--config", default=str(Path(__file__).parents[1] / "config.yaml"))
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    total: dict[str, list[float]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "timing.db"
        for path in args.audio:
            words, cues = _run(path, config, db)
            y, _ = librosa.load(path, sr=16000, mono=True)
            for k, v in score(y, words, cues).items():
                total.setdefault(k, []).extend(v)
                print(f"{Path(path).name:28s} {k:10s} {summary(v)}")
    for k, v in total.items():
        s = summary(v)
        if s["n"]:
            print(f"ALL {k:10s} n={s['n']} median {s['median_ms']:+.0f} ms, |err| median {s['median_abs_ms']:.0f} ms, "
                  f"p90 {s['p90_abs_ms']:.0f} ms, within one 25 fps frame {s['within_frame']:.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
