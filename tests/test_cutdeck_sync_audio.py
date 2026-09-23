"""Unit tests for cutdeck.sync — audio waveform cross-correlation and alignment."""

import numpy as np
import pytest

from cutdeck.contracts import Timebase
from cutdeck.sync import (
    SyncResult,
    correlate_gcc_phat,
    sync_clip_to_reference,
)


@pytest.fixture
def timebase_30():
    return Timebase(fps_num=30, fps_den=1, sample_rate=48000, duration_ms=60000)


@pytest.fixture
def timebase_2997():
    return Timebase(fps_num=30000, fps_den=1001, sample_rate=48000, duration_ms=60000)


def generate_synthetic_speech_like(duration_s: float, sr: int = 16000, seed: int = 42) -> np.ndarray:
    """Generate harmonic signal with modulated amplitude simulating speech formants."""
    np.random.seed(seed)
    t = np.linspace(0, duration_s, int(duration_s * sr), endpoint=False)
    # Fundamental + harmonics
    f0 = 150.0
    signal = (
        np.sin(2 * np.pi * f0 * t)
        + 0.6 * np.sin(2 * np.pi * 2 * f0 * t)
        + 0.4 * np.sin(2 * np.pi * 3 * f0 * t)
        + 0.2 * np.sin(2 * np.pi * 4 * f0 * t)
    )
    # Formant envelope modulation (2-4 Hz syllable rhythm)
    env = 0.5 * (1.0 + np.sin(2 * np.pi * 3.0 * t))
    return (signal * env + 0.05 * np.random.randn(len(t))).astype(np.float32)


def test_correlate_positive_offset():
    sr = 16000
    dur_ref = 30.0
    dur_clip = 10.0
    offset_s = 5.25  # Clip starts 5.25s into reference

    ref_audio = generate_synthetic_speech_like(dur_ref, sr=sr, seed=1)
    offset_samples = int(offset_s * sr)
    clip_audio = ref_audio[offset_samples : offset_samples + int(dur_clip * sr)]

    detected_offset, psr = correlate_gcc_phat(ref_audio, clip_audio, sr)

    assert abs(detected_offset - offset_s) < 0.001  # sub-millisecond
    assert psr > 20.0  # high confidence


def test_correlate_negative_offset():
    sr = 16000
    dur_total = 40.0
    dur_ref = 25.0
    dur_clip = 15.0

    # Underlying full audio
    full_audio = generate_synthetic_speech_like(dur_total, sr=sr, seed=2)

    # Ref starts at t=10.0s
    ref_audio = full_audio[int(10.0 * sr) : int((10.0 + dur_ref) * sr)]

    # Clip starts at t=6.5s (3.5s BEFORE reference!)
    clip_audio = full_audio[int(6.5 * sr) : int((6.5 + dur_clip) * sr)]
    true_offset = -3.5

    detected_offset, psr = correlate_gcc_phat(ref_audio, clip_audio, sr)

    assert abs(detected_offset - true_offset) < 0.001
    assert psr > 20.0


def test_sync_clip_exact_frames(timebase_30):
    sr = 16000
    ref_audio = generate_synthetic_speech_like(20.0, sr=sr, seed=3)

    # Offset = 3.100s -> at 30fps: 3.100 * 30 = 93 frames
    offset_s = 3.1
    clip_audio = ref_audio[int(offset_s * sr) : int((offset_s + 5.0) * sr)]

    res = sync_clip_to_reference(ref_audio, clip_audio, timebase_30, sample_rate=sr)

    assert res.is_synced is True
    assert res.offset_frames == 93
    assert res.reason == "matched"
    assert res.confidence > 15.0


def test_sync_silent_clip(timebase_30):
    sr = 16000
    ref_audio = generate_synthetic_speech_like(10.0, sr=sr, seed=4)
    silent_clip = np.zeros(int(3.0 * sr), dtype=np.float32)

    res = sync_clip_to_reference(ref_audio, silent_clip, timebase_30, sample_rate=sr)

    assert res.is_synced is False
    assert res.reason == "silent"


def test_sync_too_short_clip(timebase_30):
    sr = 16000
    ref_audio = generate_synthetic_speech_like(10.0, sr=sr, seed=5)
    short_clip = ref_audio[: int(0.2 * sr)]  # 0.2s < default 0.5s

    res = sync_clip_to_reference(ref_audio, short_clip, timebase_30, sample_rate=sr)

    assert res.is_synced is False
    assert res.reason == "too_short"


def test_sync_unrelated_audio_low_confidence(timebase_30):
    sr = 16000
    ref_audio = generate_synthetic_speech_like(15.0, sr=sr, seed=6)
    # Unrelated white noise clip
    np.random.seed(999)
    unrelated_clip = np.random.randn(int(5.0 * sr)).astype(np.float32) * 0.1

    res = sync_clip_to_reference(ref_audio, unrelated_clip, timebase_30, sample_rate=sr)

    assert res.is_synced is False
    assert res.reason == "low_confidence"
    assert res.confidence < 10.0


def test_correlate_clip_starting_past_half_the_fft_buffer():
    """Regression (2026-09-24): a clip starting late in the reference was read as a large
    NEGATIVE offset. The lag split used n_fft // 2; valid positive lags run to len(ref) - 1,
    which is past n_fft // 2 whenever len(ref) + len(clip) sits just under a power of two."""
    sr = 2000
    rng = np.random.default_rng(5)
    ref_audio = rng.standard_normal(120 * sr).astype(np.float32)  # 240000 + 16000 -> n_fft 262144
    clip_audio = ref_audio[71 * sr:79 * sr]

    detected_offset, psr = correlate_gcc_phat(ref_audio, clip_audio, sr)

    assert abs(detected_offset - 71.0) < 0.001
    assert psr > 20.0
