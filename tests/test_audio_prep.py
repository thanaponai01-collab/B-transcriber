"""Whole-file audio prep: loudness normalisation and noisy-only enhancement (transcribe/audio/prep.py).

Run: python -m pytest tests/test_audio_prep.py -v
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe.audio import prep


def _tone(seconds=3.0, amp=0.05, sr=16000):
    t = np.arange(int(seconds * sr)) / sr
    return (amp * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


def test_no_config_is_a_no_op():
    audio = _tone()
    assert prep.prepare(audio, 16000, {}) is audio


def test_loudness_reaches_target():
    pyloudnorm = pytest.importorskip("pyloudnorm")
    out = prep.loudness_normalize(_tone(), 16000, -23.0)
    assert pyloudnorm.Meter(16000).integrated_loudness(out.astype(np.float64)) == pytest.approx(-23.0, abs=0.1)


def test_loudness_never_pushes_the_peak_past_the_ceiling():
    pytest.importorskip("pyloudnorm")
    audio = _tone(amp=0.01)
    audio[100] = 0.5  # one loud click
    out = prep.loudness_normalize(audio, 16000, -10.0)
    assert 20 * np.log10(np.max(np.abs(out))) == pytest.approx(prep.PEAK_CEILING_DB, abs=0.01)


def test_enhancement_runs_only_below_the_snr_threshold(monkeypatch):
    calls = []
    monkeypatch.setattr(prep, "enhance", lambda a, sr: calls.append(1) or a)
    speech_and_silence = np.concatenate([_tone(amp=0.2), np.zeros(16000 * 3, np.float32) + 1e-4])
    noisy = speech_and_silence + np.random.default_rng(0).normal(0, 0.05, len(speech_and_silence)).astype(np.float32)
    cfg = {"audio_prep": {"enhance_below_snr_db": 21}}
    prep.prepare(speech_and_silence, 16000, cfg)
    assert calls == []
    prep.prepare(noisy, 16000, cfg)
    assert calls == [1]
