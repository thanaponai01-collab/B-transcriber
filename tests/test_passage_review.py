import numpy as np
import pytest

from transcribe.contracts import EngineResult, RecognizedToken
from transcribe.review import plan_windows, recheck_windows


def test_high_confidence_garbled_thai_still_gets_reviewed():
    cues = [{'text': 'เราเอาลยูกยัดกลับใส่ท้องไม่ได้ไงคะ', 'start_ms': 0,
             'end_ms': 2500, 'confidence': .99}]
    windows = plan_windows(cues, 2500)
    assert windows and any('unfamiliar' in r for r in windows[0].reasons)


def test_requested_passages_get_context_without_exceeding_audio():
    cues = [{'text': 'สวัสดีค่ะ', 'start_ms': i * 2000, 'end_ms': (i + 1) * 2000}
            for i in range(5)]
    windows = plan_windows(cues, 10000, requested=[(4000, 6000)], max_windows=1)
    assert windows[0].start_ms < 4000
    assert 6000 < windows[0].end_ms <= 10000


def test_engines_hear_identical_context_and_results_are_proposals_only():
    cues = [{'text': 'ต้นฉบับ', 'start_ms': 2000, 'end_ms': 4000}]
    windows = plan_windows(cues, 5000, requested=[(2000, 4000)])
    events, heard = [], []

    class FakeEngine:
        def __init__(self, name): self.name = name
        def load(self): events.append(('load', self.name))
        def unload(self): events.append(('unload', self.name))
        def transcribe(self, inp):
            heard.append(inp.audio.copy())
            assert inp.bias_terms == []  # no reference answer leaks into recognition
            return EngineResult([RecognizedToken(self.name, 0, 100, None, 'thai')], self.name)

    audio = np.arange(80000, dtype=np.float32)
    proposals = recheck_windows(audio, windows, engine_factory=FakeEngine, engines=('a', 'b'))
    assert events == [('load', 'a'), ('unload', 'a'), ('load', 'b'), ('unload', 'b')]
    assert np.array_equal(heard[0], heard[1])
    assert proposals[0]['status'] == 'needs_review'
    assert proposals[0]['alternatives'] == {'a': 'a', 'b': 'b'}
    assert proposals[0]['candidate_tokens']['a'][0]['start_ms'] == windows[0].start_ms
    assert cues[0]['text'] == 'ต้นฉบับ'


def test_failed_decode_releases_engine():
    class Broken:
        released = False
        def load(self): pass
        def transcribe(self, inp): raise RuntimeError('decode failed')
        def unload(self): self.released = True
    engine = Broken()
    windows = plan_windows([{'text': 'test', 'start_ms': 0, 'end_ms': 1000}],
                           1000, requested=[(0, 1000)])
    with pytest.raises(RuntimeError, match='decode failed'):
        recheck_windows(np.zeros(16000), windows, engine_factory=lambda _: engine, engines=('a',))
    assert engine.released


def test_requested_passages_cannot_be_silently_dropped():
    cues = [{'text': 'สวัสดีค่ะ', 'start_ms': 0, 'end_ms': 1000},
            {'text': 'สวัสดีค่ะ', 'start_ms': 20000, 'end_ms': 21000}]
    with pytest.raises(ValueError, match='budget'):
        plan_windows(cues, 21000, requested=[(0, 1000), (20000, 21000)], max_windows=1)


def test_report_treats_transcript_markup_as_data():
    from transcribe.review_report import render_review
    html = render_review({'cues': [{'text': '</script><script>alert(1)</script>'}], 'windows': []})
    assert '</script><script>alert(1)' not in html
    assert '\\u003c/script>' in html


def test_passage_display_does_not_fuse_english_cue_edges():
    class Engine:
        def load(self): pass
        def unload(self): pass
        def transcribe(self, inp):
            return EngineResult([RecognizedToken('hello', 0, 400, None, 'latin'),
                                 RecognizedToken('world', 400, 1000, None, 'latin')], 'a')
    windows = plan_windows([{'text': 'hello world', 'start_ms': 0, 'end_ms': 1000}],
                           1000, requested=[(0, 1000)])
    result = recheck_windows(np.zeros(16000), windows, engine_factory=lambda _: Engine(), engines=('a',))
    assert result[0]['alternatives']['a'] == 'hello world'
