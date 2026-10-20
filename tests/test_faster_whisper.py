"""Unit tests for FasterWhisperEngine fixes:
Issue #69:
1. self._pipeline.last_speech_timestamp is reset to 0.0 before every _pipeline.transcribe call.
2. Silent/hallucinated segments (no_speech_prob > 0.6 and avg_logprob < -1.0) are dropped
   before _words_of emits tokens, while segments meeting either threshold survive.

Issue #70:
3. Multi-window long_runs are decoded via batched clip_timestamps (batch_size=bs) rather than
   one _decode call per window, and still pass through decode_windows(..., cut_seams=True).
4. last_segment_stats includes segment stats (with global start_ms/end_ms) from long_runs
   as well as normal spans.
5. Multiple candidate truncated tails are batched together in _batch_recover_tails.
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
    seek: Optional[int] = None


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


def test_long_runs_batched_clip_timestamps_and_seam_stitching(monkeypatch):
    from transcribe.audio import Window
    import transcribe.engines.faster_whisper as fw

    engine = fw.FasterWhisperEngine()
    audio = np.zeros(50 * fw._SR, dtype=np.float32)

    # Simulate speech_windows returning 1 long run with 2 overlapping windows
    # Window 0: 0.0s - 25.0s, Window 1: 21.0s - 46.0s (span_index 0)
    w0 = Window(0.0, 25.0, span_index=0)
    w1 = Window(21.0, 46.0, span_index=0)
    monkeypatch.setattr(fw, "speech_windows", lambda a, p: [w0, w1])

    calls = []

    def fake_decode(audio_arr, clip_timestamps, vad_filter, common_kwargs, bs):
        calls.append({
            "len_audio": len(audio_arr),
            "clip_timestamps": clip_timestamps,
            "bs": bs,
        })
        # Window 0 produces word "ข้อที่หนึ่ง" at 10.0-12.0s and seam word "ทับซ้อน" at 22.0-24.0s (ends 1s before window end)
        # Window 1 produces seam word "ทับซ้อน" at 22.0-24.0s and word "ข้อที่สอง" at 43.0-45.2s (ends 0.8s before window end)
        seg0 = FakeSegment(
            words=[FakeWord(" ข้อที่หนึ่ง", 10.0, 12.0), FakeWord(" ทับซ้อน", 22.0, 24.0)],
            start=10.0, end=24.0, avg_logprob=-0.2, no_speech_prob=0.01, seek=0,
        )
        seg1 = FakeSegment(
            words=[FakeWord(" ทับซ้อน", 22.0, 24.0), FakeWord(" ข้อที่สอง", 43.0, 45.2)],
            start=22.0, end=45.2, avg_logprob=-0.15, no_speech_prob=0.02, seek=2100,
        )
        return [seg0, seg1], bs

    engine._decode = fake_decode
    words = engine._transcribe_batched(audio, "th", None)

    # 1. Multi-window long_runs must be decoded via a SINGLE batched call with clip_timestamps
    assert len(calls) == 1
    assert calls[0]["bs"] == 8
    assert calls[0]["clip_timestamps"] == [
        {"start": 0.0, "end": 25.0},
        {"start": 21.0, "end": 46.0},
    ]

    # 2. Output must pass through decode_windows cut_seams/stitch (duplicate 'ทับซ้อน' deduplicated)
    texts = [w[0].strip() for w in words]
    assert texts == ["ข้อที่หนึ่ง", "ทับซ้อน", "ข้อที่สอง"]

    # 3. last_segment_stats must record stats for long_runs with global timestamps
    stats = engine.last_segment_stats
    assert len(stats) == 2
    assert stats[0]["start_ms"] == 10000
    assert stats[0]["end_ms"] == 24000
    assert stats[0]["avg_logprob"] == -0.2
    assert stats[1]["start_ms"] == 22000
    assert stats[1]["end_ms"] == 45200
    assert stats[1]["avg_logprob"] == -0.15


def test_segment_stats_recorded_for_both_normal_and_long_runs(monkeypatch):
    from transcribe.audio import Window
    import transcribe.engines.faster_whisper as fw

    engine = fw.FasterWhisperEngine()
    audio = np.zeros(60 * fw._SR, dtype=np.float32)

    # 1 normal span (span_index 0) and 1 long span (span_index 1 with 2 windows)
    w_norm = Window(2.0, 8.0, span_index=0)
    w_long0 = Window(15.0, 40.0, span_index=1)
    w_long1 = Window(36.0, 60.0, span_index=1)
    monkeypatch.setattr(fw, "speech_windows", lambda a, p: [w_norm, w_long0, w_long1])

    calls = []

    def fake_decode(audio_arr, clip_timestamps, vad_filter, common_kwargs, bs):
        calls.append(clip_timestamps)
        if len(clip_timestamps) == 1:  # normal span
            seg = FakeSegment(
                words=[FakeWord(" ธรรมดา", 3.0, 7.2)],
                start=3.0, end=7.2, avg_logprob=-0.3, no_speech_prob=0.05,
            )
            return [seg], bs
        else:  # long run
            seg0 = FakeSegment(
                words=[FakeWord(" ยาวหนึ่ง", 20.0, 39.0)],
                start=20.0, end=39.0, avg_logprob=-0.25, no_speech_prob=0.03, seek=1500,
            )
            seg1 = FakeSegment(
                words=[FakeWord(" ยาวสอง", 45.0, 59.2)],
                start=45.0, end=59.2, avg_logprob=-0.1, no_speech_prob=0.01, seek=3600,
            )
            return [seg0, seg1], bs

    engine._decode = fake_decode
    words = engine._transcribe_batched(audio, "th", None)

    assert len(calls) == 2
    assert calls[0] == [{"start": 2.0, "end": 8.0}]
    assert calls[1] == [{"start": 15.0, "end": 40.0}, {"start": 36.0, "end": 60.0}]

    stats = engine.last_segment_stats
    assert len(stats) == 3
    # Check that normal and long-runs stats are both recorded with global timestamps
    assert stats[0]["start_ms"] == 3000
    assert stats[1]["start_ms"] == 20000
    assert stats[2]["start_ms"] == 45000


def test_long_runs_batched_tail_recoveries(monkeypatch):
    """When multiple windows in long_runs experience truncation, candidate tails
    are batched together into a single combined decode rather than sequential batch_size=1 calls."""
    from transcribe.audio import Window
    import transcribe.engines.faster_whisper as fw

    engine = fw.FasterWhisperEngine()
    audio = np.zeros(60 * fw._SR, dtype=np.float32)

    # 2 windows in long_runs:
    # Window 0: 0.0s - 25.0s, last word ends early at 15.0s (trailing gap 10s >= 1.5s -> needs tail recovery)
    # Window 1: 21.0s - 46.0s, last word ends early at 35.0s (trailing gap 11s >= 1.5s -> needs tail recovery)
    w0 = Window(0.0, 25.0, span_index=0)
    w1 = Window(21.0, 46.0, span_index=0)
    monkeypatch.setattr(fw, "speech_windows", lambda a, p: [w0, w1])

    calls = []

    def fake_decode(audio_arr, clip_timestamps, vad_filter, common_kwargs, bs):
        calls.append({
            "len_audio": len(audio_arr),
            "clip_timestamps": clip_timestamps,
            "bs": bs,
        })
        if len(calls) == 1:
            # Initial batched decode of the 2 windows
            seg0 = FakeSegment(
                words=[FakeWord(" ต้น", 5.0, 6.0), FakeWord(" จบก่อน", 14.0, 15.0)],
                start=5.0, end=15.0, avg_logprob=-0.2, no_speech_prob=0.01, seek=0,
            )
            seg1 = FakeSegment(
                words=[FakeWord(" กลาง", 25.0, 26.0), FakeWord(" จบก่อนสอง", 34.0, 35.0)],
                start=25.0, end=35.0, avg_logprob=-0.2, no_speech_prob=0.01, seek=2100,
            )
            return [seg0, seg1], bs
        else:
            # Batched recovery call! Both candidate tails are combined into 1 call
            # clip 0: 0 to 10s (tail of window 0), clip 1: 10 to 21s (tail of window 1)
            seg_rec0 = FakeSegment(
                words=[FakeWord(" ต่อหนึ่ง", 1.0, 2.0)],
                start=1.0, end=2.0, avg_logprob=-0.1, no_speech_prob=0.01, seek=0,
            )
            seg_rec1 = FakeSegment(
                words=[FakeWord(" ต่อสอง", 11.0, 12.0)],
                start=11.0, end=12.0, avg_logprob=-0.1, no_speech_prob=0.01, seek=1000,
            )
            return [seg_rec0, seg_rec1], bs

    engine._decode = fake_decode
    words = engine._transcribe_batched(audio, "th", None)

    # Total calls must be exactly 2:
    # Call 1: initial batched decode of both windows
    # Call 2: BATCHED recovery of both candidate tails in a single decode
    assert len(calls) == 2
    assert len(calls[0]["clip_timestamps"]) == 2
    assert len(calls[1]["clip_timestamps"]) == 2
    # Verify recovered words present
    texts = [w[0].strip() for w in words]
    assert "ต่อหนึ่ง" in texts
    assert "ต่อสอง" in texts
