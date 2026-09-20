"""Review selected passages from a saved job without modifying its transcript.

python -m tools.recheck_subtitles 44 --output output/review44
Optional --window START:END uses seconds and can be repeated; --plan-only skips ASR.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from transcribe.db import store
from transcribe.review import plan_windows, recheck_windows
from transcribe.review_report import render_review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job_id', type=int)
    parser.add_argument('--db', type=Path, default=Path('transcriber.db'))
    parser.add_argument('--config', type=Path, default=Path('transcribe/config.yaml'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--window', action='append', default=[], metavar='START:END')
    parser.add_argument('--max-windows', type=int, default=6)
    parser.add_argument('--plan-only', action='store_true')
    args = parser.parse_args()
    from contextlib import closing
    with closing(store.connect(args.db)) as conn:
        job = store.get_job(conn, args.job_id)
        if job is None:
            raise ValueError('Job not found')
        media = store.get_media(conn, job.media_id)
        corrections = {c.token_idx: c.corrected_text for c in store.get_corrections(conn, args.job_id)}
        cues = [{**asdict(t), 'text': corrections.get(t.idx, t.text)}
                for t in store.get_tokens(conn, args.job_id)]
    if not media or not cues:
        raise ValueError('Job has no audio or transcript')
    # Heavy dependencies are loaded only when the command actually runs.
    import soundfile as sf
    import torch
    import yaml
    from transcribe.pipeline.ingest import load_audio
    from transcribe.pipeline.engine_run import build_engine

    audio, sr = load_audio(media.path)
    if sr != 16000:
        raise ValueError('Review requires 16kHz decoded audio')
    requested = [tuple(round(float(x) * 1000) for x in value.split(':')) for value in args.window]
    windows = plan_windows(cues, round(len(audio) * 1000 / sr), requested=requested,
                           max_windows=args.max_windows)
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'job_id': args.job_id, 'audio_sha256': store.sha256_of_file(media.path),
              'cues': cues, 'windows': [asdict(w) for w in windows],
              'mode': 'plan' if args.plan_only else 'review'}
    (args.output / 'plan.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    for w in windows:
        print(f'{w.start_ms/1000:.2f}–{w.end_ms/1000:.2f}s: {"; ".join(w.reasons)}', flush=True)
    if args.plan_only:
        return
    config = yaml.safe_load(args.config.read_text(encoding='utf-8'))
    # Small review batches bound VRAM; adapters are unloaded sequentially.
    config.setdefault('engines', {}).setdefault('qwen3_asr', {})['max_inference_batch_size'] = 2
    report['windows'] = recheck_windows(audio, windows,
        engine_factory=lambda name: build_engine(name, 'cuda' if torch.cuda.is_available() else 'cpu', config))
    clips = args.output / 'audio'
    clips.mkdir(exist_ok=True)
    for i, w in enumerate(windows, 1):
        sf.write(clips / f'{i:03d}.wav', audio[w.start_ms*16:w.end_ms*16], sr)
    (args.output / 'review.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (args.output / 'review.html').write_text(render_review(report), encoding='utf-8')
    print(f'Review ready: {args.output / "review.html"}', flush=True)


if __name__ == '__main__':
    main()
