"""Seconds per pipeline stage on one fixed benchmark file (timers wrapped around the stage
functions from outside; the pipeline itself is unchanged).

The benchmark is 600 s of the 2026-09-05 qualifying stream (in no judge split) from 1200 s, 16 kHz mono. Each run uses a
fresh database, so nothing is reused from a cache. The GPU is shared with whatever else is running
(Premiere): run it twice and compare."""
from __future__ import annotations

import argparse
import functools
import json
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

from transcribe.eval.judge.prepare import REPO

BENCH_SRC = "E:/Me/2.Tasks/20260905 - 2/1. FOOTAGE/q/2026-09-05 20-31-53.mp4"
BENCH = Path("E:/Me/5.Claude/Transcriber_v2/output/timing/bench_q0905_600.wav")

TIMERS: dict[str, float] = defaultdict(float)
CALLS: dict[str, int] = defaultdict(int)


def _wrap(owner, attr: str, stage: str) -> None:
    fn = getattr(owner, attr)

    @functools.wraps(fn)
    def timed(*a, **k):
        t = time.perf_counter()
        try:
            return fn(*a, **k)
        finally:
            TIMERS[stage] += time.perf_counter() - t
            CALLS[stage] += 1
    setattr(owner, attr, timed)


def instrument() -> None:
    from transcribe.cues import split as cue_split
    from transcribe.engines import faster_whisper
    from transcribe.pipeline import align_force, ingest, word_align
    _wrap(ingest, "load_audio", "decode")
    _wrap(ingest, "_apply_rolling_denoise", "denoise")
    _wrap(ingest, "_vad_chunks", "vad")
    _wrap(ingest, "sound_runs", "vad")
    _wrap(faster_whisper.FasterWhisperEngine, "load", "whisper_load")
    _wrap(faster_whisper.FasterWhisperEngine, "transcribe", "whisper_transcribe")
    _wrap(faster_whisper.FasterWhisperEngine, "_release", "whisper_unload")
    _wrap(faster_whisper, "split_cues", "cue_split")
    _wrap(align_force, "forced_align", "post_engine")
    _wrap(word_align, "levels_db", "ctc_levels")
    _wrap(word_align.ThaiCTCAligner, "load", "ctc_load")
    _wrap(word_align.ThaiCTCAligner, "__call__", "ctc_align")
    _wrap(word_align.ThaiCTCAligner, "unload", "ctc_unload")
    _wrap(word_align, "retime_words", "retime_words")


def bench_file() -> Path:
    if not BENCH.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1200", "-t", "600", "-i", BENCH_SRC,
                        "-vn", "-ac", "1", "-ar", "16000", str(BENCH)], check=True)
    return BENCH


def main(argv: list[str] | None = None) -> int:
    import yaml
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--config", default=str(REPO / "transcribe" / "config.yaml"))
    p.add_argument("--label", default="baseline")
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    path = bench_file()
    instrument()
    from transcribe.pipeline import run as pipeline_run
    with tempfile.TemporaryDirectory() as tmp:
        t = time.perf_counter()
        pipeline_run.run_file_job(str(path), config, Path(tmp) / "bench.db")
        total = time.perf_counter() - t
    stages = {k: round(v, 2) for k, v in TIMERS.items()}
    stages["snap_and_retime"] = round(TIMERS["retime_words"] - TIMERS["ctc_align"], 2)
    stages["other"] = round(total - sum(v for k, v in TIMERS.items() if k not in ("ctc_align", "cue_split")), 2)
    out = {"label": args.label, "file_s": 600, "total_s": round(total, 2), "x_realtime": round(600 / total, 2),
           "stages": stages, "calls": dict(CALLS), "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    runs = REPO / "output" / "judge_runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{time.strftime('%Y%m%d-%H%M%S')}-speed-{args.label}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
