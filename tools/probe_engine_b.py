"""Isolated Qwen Engine B probe; does not change production config or its DB.

Reports raw A, raw B and select-only A+B before normalization/timing refinement.
The reference is used only for scoring, never supplied to the model.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

from transcribe.contracts import EngineInput, RecognizedToken
from transcribe.engines.registry import get_engine
from transcribe.eval.metrics import compute_metrics
from transcribe.pipeline.align_hyp import align
from transcribe.pipeline.ingest import load_audio
from transcribe.pipeline.reconcile import reconcile
from transcribe.subtitles import read_subtitles, write_subtitles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--engine-a-json', type=Path, required=True,
                        help='Cached JSON object containing a tokens list')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-span-s', type=float, default=8.0)
    parser.add_argument('--batch-size', type=int, default=2)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    gold = read_subtitles(args.reference.read_text(encoding='utf-8-sig'))
    a = json.loads(args.engine_a_json.read_text(encoding='utf-8'))['tokens']
    audio, sr = load_audio(str(args.audio))
    if sr != 16000 or not gold:
        raise ValueError('Expected 16kHz decoded audio and a nonempty reference')
    engine = get_engine('qwen3_asr', device='cuda',
                        max_inference_batch_size=args.batch_size,
                        max_span_s=args.max_span_s)
    started = time.monotonic()
    try:
        engine.load()
        result = engine.transcribe(EngineInput(audio=audio, language_hint='th'))
    finally:
        engine.unload()
    b = [asdict(t) for t in result.tokens]
    combined = [asdict(t) for t, _ in reconcile(
        align([RecognizedToken(**t) for t in a], result.tokens))]
    report = {
        'seconds': time.monotonic() - started,
        'max_span_s': args.max_span_s,
        'batch_size': args.batch_size,
        'stage': 'raw hypotheses and reconciliation; before refinement',
        'a': asdict(compute_metrics(gold, a)),
        'b': asdict(compute_metrics(gold, b)),
        'combined': asdict(compute_metrics(gold, combined)),
    }
    for name, value in [('engine-b.json', b), ('report.json', report)]:
        (args.output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    (args.output / 'engine-b.srt').write_text(write_subtitles(b, 'srt'), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
