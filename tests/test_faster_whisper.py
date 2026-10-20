"""Unit tests for FasterWhisperEngine fixes in issue #69:
1. self._pipeline.last_speech_timestamp is reset to 0.0 before every _pipeline.transcribe call.
2. Silent/hallucinated segments (no_speech_prob > 0.6 and avg_logprob < -1.0) are dropped
   before _words_of emits tokens, while segments meeting either threshold survive.
"""
from dataclasses import dataclass
from typing import Optional
import numpy as np
import pytest

from transcribe.contracts import RecognizedToken
from transcribe.engines.faster_whisper import FasterWhisperEngine


@dataclass
class FakeWord:
    word: str
    start: float
    end: float
    probability: float = 0.9


@dataclass
class FakeSegment:
    words: list[FakeWord]
    no_speech_prob: Optional[float] = 0.0
    avg_logprob: Optional[float] = 0.0
    start: float = 0.0
    end: float = 1.0
    text: str = ""
    compression_ratio: float = 1.0


class FakeBatchedPipeline:
    def __init__(self):
        self.last_speech_timestamp = 150.0
        self.transcribe_calls = []

    def transcribe(self, audio_arr, vad_filter=False, clip_timestamps=None, batch_size=8, **kwargs):
        self.transcribe_calls.append({
            "last_speech_timestamp_at_call": self.last_speech_timestamp,
            "batch_size": batch_size,
            "clip_timestamps": clip_timestamps,
            "kwargs": kwargs,
        })
        self.last_speech_timestamp = 500.0
        return [FakeSegment(words=[FakeWord("สวัสดี", 0.0, 1.0)], no_speech_prob=0.01, avg_logprob=-0.2)], None


def test_decode_resets_last_speech_timestamp_per_call():
    engine = FasterWhisperEngine.__new__(FasterWhisperEngine)
    engine._pipeline = FakeBatchedPipeline()

    audio = np.zeros(16000, dtype=np.float32)
    # First decode call
    segs1, bs1 = engine._decode(audio, clip_timestamps=None, vad_filter=False, common_kwargs={}, bs=4)
    assert len(engine._pipeline.transcribe_calls) == 1
    assert engine._pipeline.transcribe_calls[0]["last_speech_timestamp_at_call"] == 0.0
    # Simulate that transcribe left last_speech_timestamp mutated
    assert engine._pipeline.last_speech_timestamp == 500.0

    # Second decode call (e.g. local-window re-decode or long_runs window)
    segs2, bs2 = engine._decode(audio, clip_timestamps=None, vad_filter=False, common_kwargs={}, bs=4)
    assert len(engine._pipeline.transcribe_calls) == 2
    assert engine._pipeline.transcribe_calls[1]["last_speech_timestamp_at_call"] == 0.0


def test_words_of_drops_silent_garbage_segments():
    seg_silent = FakeSegment(
        words=[FakeWord(" hallucination", 0.0, 1.0)],
        no_speech_prob=0.85,
        avg_logprob=-1.5,
    )
    seg_good = FakeSegment(
        words=[FakeWord(" สวัสดี", 1.0, 2.0)],
        no_speech_prob=0.05,
        avg_logprob=-0.2,
    )
    seg_high_no_speech_high_logprob = FakeSegment(
        words=[FakeWord(" highlogprob", 2.0, 3.0)],
        no_speech_prob=0.8,
        avg_logprob=-0.5,
    )
    seg_low_no_speech_low_logprob = FakeSegment(
        words=[FakeWord(" lownospeech", 3.0, 4.0)],
        no_speech_prob=0.2,
        avg_logprob=-1.5,
    )

    segments = [seg_silent, seg_good, seg_high_no_speech_high_logprob, seg_low_no_speech_low_logprob]
    tokens = FasterWhisperEngine._words_of(segments)
    texts = [t.text.strip() for t in tokens]

    assert "hallucination" not in texts
    assert "สวัสดี" in texts
    assert "highlogprob" in texts
    assert "lownospeech" in texts


def test_words_of_boundary_and_custom_thresholds():
    # Boundary: exactly 0.6 and -1.0 should survive (must be strictly > 0.6 and < -1.0 to drop)
    seg_edge = FakeSegment(
        words=[FakeWord(" edge", 0.0, 1.0)],
        no_speech_prob=0.6,
        avg_logprob=-1.0,
    )
    assert len(FasterWhisperEngine._words_of([seg_edge])) == 1

    # Strictly past threshold -> dropped
    seg_dropped = FakeSegment(
        words=[FakeWord(" drop", 0.0, 1.0)],
        no_speech_prob=0.6001,
        avg_logprob=-1.0001,
    )
    assert len(FasterWhisperEngine._words_of([seg_dropped])) == 0

    # Custom thresholds
    seg_custom = FakeSegment(
        words=[FakeWord(" custom", 0.0, 1.0)],
        no_speech_prob=0.75,
        avg_logprob=-1.2,
    )
    # Default (0.6, -1.0) drops it:
    assert len(FasterWhisperEngine._words_of([seg_custom])) == 0
    # Custom threshold (no_speech_threshold=0.8) keeps it:
    assert len(FasterWhisperEngine._words_of([seg_custom], no_speech_threshold=0.8, log_prob_threshold=-1.0)) == 1


def test_faster_whisper_engine_init_threshold_attributes():
    engine = FasterWhisperEngine(
        no_speech_threshold=0.7,
        log_prob_threshold=-1.2,
        compression_ratio_threshold=2.0,
    )
    assert engine._no_speech_threshold == 0.7
    assert engine._log_prob_threshold == -1.2
    assert engine._compression_ratio_threshold == 2.0
