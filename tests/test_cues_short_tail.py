"""Regression from job 44: length limits stranded a 240ms Thai final word."""
import json
from pathlib import Path

from transcribe.cues import split_cues
from transcribe.cues.policy import CuePolicy


def test_real_recognition_does_not_strand_trailing_word():
    words = json.loads((Path(__file__).parent / 'fixtures/shorts_trailing_word.json').read_text(encoding='utf-8'))
    pieces = [(w['text'], w['start_ms'], w['end_ms'], w['confidence']) for w in words]
    cues = split_cues(pieces)
    assert not any(t == 'อีก' and e - s < 500 for t, s, e, _ in cues)
    assert ''.join(t for t, *_ in cues) == ''.join(w[0] for w in pieces).strip()
    assert cues[0][1] == 24480 and cues[-1][2] == 26640


def test_short_tail_does_not_cross_real_pause():
    cues = split_cues([('hello world', 0, 1500, None), (' yes', 2500, 2700, None)],
                      CuePolicy(target_chars=10))
    assert cues[-1][:3] == ('yes', 2500, 2700)


def test_short_tail_does_not_cross_sentence_boundary(monkeypatch):
    monkeypatch.setattr('transcribe.cues.split._sentence_boundary_offsets', lambda _: [12])
    cues = split_cues([('hello world', 0, 1500, None), (' yes', 1500, 1700, None)],
                      CuePolicy(target_chars=10))
    assert cues[-1][0] == 'yes'
