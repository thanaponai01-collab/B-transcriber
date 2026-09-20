"""Compare an exported SRT with a hand-corrected reference, without running ASR.

python -m tools.compare_subtitles corrected.srt candidate.srt [--output report.json]
Text scores ignore display wrapping; layout and short cues are reported separately.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import re

from transcribe.eval.metrics import compute_metrics
from transcribe.subtitles import read_subtitles


def compare(reference: str, candidate: str) -> dict:
    ref = read_subtitles(reference)
    hyp = read_subtitles(candidate)
    if not ref or not hyp:
        raise ValueError('Both files must contain subtitle cues')

    def stats(raw, cues):
        return {
            'cue_count': len(cues),
            'multiline_cues': sum(len(block.strip().splitlines()) > 3
                                   for block in re.split(r'\r?\n\s*\r?\n', raw.strip())),
            'under_500ms': [{'text': c['text'], 'start_ms': c['start_ms'],
                             'duration_ms': c['end_ms'] - c['start_ms']}
                            for c in cues if c['end_ms'] - c['start_ms'] < 500],
        }

    return {'metrics': asdict(compute_metrics(ref, hyp)),
            'reference': stats(reference, ref), 'candidate': stats(candidate, hyp)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = compare(args.reference.read_text(encoding='utf-8-sig'),
                     args.candidate.read_text(encoding='utf-8-sig'))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + '\n', encoding='utf-8')
    print(rendered)


if __name__ == '__main__':
    main()
