"""Fit a personal layout profile or apply it without changing cue timing.

python -m tools.subtitle_layout learn corrected1.srt corrected2.srt --output style.json
python -m tools.subtitle_layout apply source.srt --profile style.json --output laid-out.srt
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from transcribe.subtitles import read_subtitles, write_subtitles
from transcribe.subtitles.layout import LayoutProfile, fit_profile, layout_cues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    learn = sub.add_parser('learn')
    learn.add_argument('references', nargs='+', type=Path)
    learn.add_argument('--output', required=True, type=Path)
    apply = sub.add_parser('apply')
    apply.add_argument('source', type=Path)
    apply.add_argument('--profile', required=True, type=Path)
    apply.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.command == 'learn':
        references = [p.read_text(encoding='utf-8-sig') for p in args.references]
        profile = fit_profile(references)
        document = {'profile': asdict(profile), 'sources': [
            {'name': p.name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in args.references]}
        args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(document, ensure_ascii=False, indent=2))
    else:
        if args.source.resolve() == args.output.resolve():
            raise ValueError('Choose a separate output to preserve the source subtitles')
        profile = LayoutProfile(**json.loads(args.profile.read_text(encoding='utf-8'))['profile'])
        cues = read_subtitles(args.source.read_text(encoding='utf-8-sig'), preserve_line_breaks=True)
        result = layout_cues(cues, profile)
        args.output.write_text(write_subtitles(result, 'srt'), encoding='utf-8')
        print(f'{len(result)} cues; {sum(chr(10) in c["text"] for c in result)} multiline; timings preserved')


if __name__ == '__main__':
    main()
