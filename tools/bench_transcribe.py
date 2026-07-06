"""Benchmark faster-whisper: realtime factor + batched-vs-sequential equivalence (3.1).

    python -m tools.bench_transcribe path/to/clip.wav
    python -m tools.bench_transcribe path/to/clip.wav --compare-sequential

Reports realtime factor (audio_seconds / wall_seconds). --compare-sequential also
runs the old whole-file sequential path and prints the char-level CER between the
two transcripts — the acceptance gate is <1% (batching must not change output).

Record the numbers in TODO_LEDGER.md. The meaningful run is a ~5-min real clip on
the RTX 3070; target ≥3× the sequential path.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _rtf(audio_seconds: float, wall: float) -> float:
    return audio_seconds / wall if wall else float("inf")


def _text_of(segments) -> str:
    return "".join(w.word for seg in segments for w in (seg.words or []))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--compare-sequential", action="store_true")
    args = ap.parse_args()

    import torch
    from transcribe.pipeline.ingest import load_audio
    from transcribe.engines.faster_whisper import FasterWhisperEngine
    from transcribe.contracts import EngineInput

    device = "cuda" if torch.cuda.is_available() else "cpu"
    audio, sr = load_audio(args.audio)
    audio_seconds = len(audio) / sr
    print(f"[bench] {args.audio}: {audio_seconds:.1f}s audio on {device}")

    eng = FasterWhisperEngine(device=device, batch_size=args.batch_size)
    eng.load()

    t0 = time.perf_counter()
    res = eng.transcribe(EngineInput(audio=audio, language_hint="th"))
    batched_wall = time.perf_counter() - t0
    batched_text = "".join(t.text for t in res.tokens)
    print(f"[bench] batched(bs={args.batch_size}): {batched_wall:.1f}s wall  "
          f"→ {_rtf(audio_seconds, batched_wall):.2f}× realtime  ({len(res.tokens)} cues)")

    if args.compare_sequential:
        from transcribe.eval.metrics import _edit_distance
        t0 = time.perf_counter()
        segs, _ = eng._model.transcribe(
            audio, language="th", task="transcribe", beam_size=5, word_timestamps=True,
            vad_filter=True, condition_on_previous_text=False,
            compression_ratio_threshold=2.4, log_prob_threshold=-1.0, no_speech_threshold=0.6,
        )
        seq_text = _text_of(list(segs))
        seq_wall = time.perf_counter() - t0
        print(f"[bench] sequential:        {seq_wall:.1f}s wall  "
              f"→ {_rtf(audio_seconds, seq_wall):.2f}× realtime")
        print(f"[bench] speedup: {seq_wall / batched_wall:.2f}× over sequential")
        cer = _edit_distance(seq_text, batched_text) / max(1, len(seq_text))
        verdict = "OK" if cer < 0.01 else "FAIL (>1%)"
        print(f"[bench] batched-vs-sequential CER: {cer:.4%}  [{verdict}]")

    eng.unload()


if __name__ == "__main__":
    main()
