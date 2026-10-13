"""Short-span recovery exercises the real batch path without model inference."""
import numpy as np
import pytest

import transcribe.engines.faster_whisper as fw
from transcribe.audio import Window
from transcribe.contracts import RecognizedToken


class Word:
    def __init__(self, text, start, end):
        self.word, self.start, self.end, self.probability = text, start, end, 0.9


class Segment:
    def __init__(self, words):
        self.words = words


def test_recovers_tail_in_short_span_with_absolute_timestamps(monkeypatch):
    engine = fw.FasterWhisperEngine(recover_short_spans=True)
    audio = np.ones(12 * fw._SR, dtype=np.float32)
    calls = []
    monkeypatch.setattr(fw, 'speech_windows', lambda a, p: [Window(3, 10, 0)]
                        if a is audio else [Window(0, len(a) / fw._SR, 0)])

    def decode(a, clips, vad, common, bs):
        calls.append((len(a), clips))
        if a is audio:
            return [Segment([Word(' heard', 3, 4)])], bs
        return [Segment([Word(' recovered', 0, 1)])], 4

    engine._decode = decode
    result = engine._transcribe_batched(audio, 'th', None)
    assert [w[:3] for w in result] == [(' heard', 3000, 4000), (' recovered', 4000, 5000)]
    assert len(calls) == 2
    assert calls[1][0] == 6 * fw._SR  # only this span's tail, never the next span


def test_empty_short_span_retries_once_without_touching_other_spans(monkeypatch):
    engine = fw.FasterWhisperEngine(recover_short_spans=True)
    audio = np.ones(16 * fw._SR, dtype=np.float32)
    calls = []
    monkeypatch.setattr(fw, 'speech_windows', lambda a, p:
                        [Window(2, 6, 0), Window(10, 14, 1)] if a is audio
                        else [Window(0, len(a) / fw._SR, 0)])

    def decode(a, clips, vad, common, bs):
        calls.append(clips)
        if a is audio:
            return [Segment([Word(' intact', 10, 13)])], bs
        return [Segment([Word(' recovered', 0, 1)])], bs

    engine._decode = decode
    result = engine._transcribe_batched(audio, 'th', None)
    assert [w[:3] for w in result] == [(' recovered', 2000, 3000), (' intact', 10000, 13000)]
    assert len(calls) == 2


@pytest.mark.parametrize('empty', [False, True])
def test_silence_tail_does_not_trigger_retry(monkeypatch, empty):
    engine = fw.FasterWhisperEngine(recover_short_spans=True)
    monkeypatch.setattr(fw, 'speech_windows', lambda *a: [])
    engine._decode = lambda *a: pytest.fail('silence must never be retried')
    tokens = [] if empty else [RecognizedToken('heard', 0, 500, 0.9, 'latin')]
    recovered, bs = engine._recover_truncated_tail(
        tokens, np.zeros(4 * fw._SR, dtype=np.float32), {}, 8, require_speech=True)
    assert recovered is tokens
    assert bs == 8


def test_empty_retry_is_bounded_when_decoder_still_returns_nothing(monkeypatch):
    engine = fw.FasterWhisperEngine(recover_short_spans=True)
    monkeypatch.setattr(fw, 'speech_windows', lambda a, p: [Window(0, 3, 0)])
    calls = []
    engine._decode = lambda *a: (calls.append(True) or [], 4)
    recovered, bs = engine._recover_truncated_tail(
        [], np.ones(3 * fw._SR, dtype=np.float32), {}, 8, require_speech=True)
    assert recovered == []
    assert bs == 4
    assert len(calls) == 1


def test_disabled_flag_preserves_original_batch_path(monkeypatch):
    engine = fw.FasterWhisperEngine(recover_short_spans=False)
    audio = np.ones(10 * fw._SR, dtype=np.float32)
    monkeypatch.setattr(fw, 'speech_windows', lambda *a: [Window(2, 8, 0)])
    engine._decode = lambda *a: ([Segment([Word(' original', 2, 3)])], 8)
    engine._recover_truncated_tail = lambda *a, **k: pytest.fail('flag is disabled')
    assert engine._transcribe_batched(audio, 'th', None) == [(' original', 2000, 3000, 0.9)]

def test_retry_uses_detected_speech_clips_and_keeps_their_offset(monkeypatch):
    engine = fw.FasterWhisperEngine(recover_short_spans=True)
    monkeypatch.setattr(fw, 'speech_windows', lambda a, p: [Window(1, 3, 0)])
    captured = []

    def decode(a, clips, vad, common, bs):
        captured.append(clips)
        return [Segment([Word(' recovered', 1, 2)])], 4

    engine._decode = decode
    original = [RecognizedToken(' heard', 0, 1000, 0.9, 'latin')]
    result, bs = engine._recover_truncated_tail(
        original, np.ones(5 * fw._SR), {}, 8, require_speech=True)
    assert captured == [[{'start': 1, 'end': 3}]]
    assert [(t.start_ms, t.end_ms) for t in result] == [(0, 1000), (2000, 3000)]
    assert bs == 4


def test_stretched_last_word_is_preserved_when_retry_region_has_no_speech(monkeypatch):
    engine = fw.FasterWhisperEngine(recover_short_spans=True)
    monkeypatch.setattr(fw, 'speech_windows', lambda *a: [])
    engine._decode = lambda *a: pytest.fail('silence must never be retried')
    tokens = [RecognizedToken('one', 0, 200, 0.9, 'latin'),
              RecognizedToken('two', 1000, 1200, 0.9, 'latin'),
              RecognizedToken('suspect', 1200, 4000, 0.9, 'latin')]
    result, bs = engine._recover_truncated_tail(
        tokens, np.zeros(5 * fw._SR), {}, 8, require_speech=True)
    assert result is tokens
    assert bs == 8

def test_recovery_setting_reaches_engine_through_pipeline_config():
    from transcribe.pipeline.engine_run import build_engine
    engine = build_engine('faster_whisper', 'cpu', {
        'engines': {'faster_whisper': {'recover_short_spans': True}}})
    assert engine._recover_short_spans is True


def test_real_vad_rejects_silence_without_loading_asr():
    engine = fw.FasterWhisperEngine(recover_short_spans=True)
    engine._decode = lambda *a: pytest.fail('silence must never reach ASR')
    result, bs = engine._recover_truncated_tail(
        [], np.zeros(3 * fw._SR, dtype=np.float32), {}, 8, require_speech=True)
    assert result == []
    assert bs == 8
