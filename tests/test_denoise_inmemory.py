"""Phase 4.4 — rolling denoise runs in-memory, no temp WAV per window.

The old `_denoise_window` wrote+read a temp WAV file per 2s window purely to
satisfy DeepFilterNet's `load_audio(path, sr)` signature. Verify the tensor is
built directly from the numpy window and no tempfile/soundfile-write path is
exercised, using a fake model/df_state/enhance_fn (DeepFilterNet itself need
not be installed for this test).
"""

from unittest.mock import MagicMock, patch

import numpy as np

from transcribe.pipeline import ingest


class _FakeDFState:
    def __init__(self, sr):
        self._sr = sr

    def sr(self):
        return self._sr


def test_denoise_window_stays_in_memory_same_sample_rate():
    sr = 16000
    window = np.random.uniform(-0.1, 0.1, sr * 2).astype(np.float32)
    df_state = _FakeDFState(sr)
    model = object()

    def fake_enhance(m, state, audio_t):
        assert audio_t.shape[0] == 1  # (channels, samples) as built in-memory
        return audio_t.squeeze(0)

    with patch("tempfile.NamedTemporaryFile") as mock_tmp, \
         patch("soundfile.write") as mock_write:
        out = ingest._denoise_window(window, sr, model, df_state, fake_enhance)

    mock_tmp.assert_not_called()
    mock_write.assert_not_called()
    assert out.shape == window.shape
    assert out.dtype == np.float32


def test_denoise_window_resamples_when_df_rate_differs():
    sr = 16000
    df_sr = 48000
    window = np.random.uniform(-0.1, 0.1, sr).astype(np.float32)
    df_state = _FakeDFState(df_sr)
    model = object()

    def fake_enhance(m, state, audio_t):
        return audio_t.squeeze(0)

    out = ingest._denoise_window(window, sr, model, df_state, fake_enhance)
    assert out.dtype == np.float32
    assert len(out) == len(window)  # resampled back down to the original sr


def test_denoise_window_falls_back_to_original_on_failure():
    sr = 16000
    window = np.ones(sr, dtype=np.float32) * 0.5
    df_state = _FakeDFState(sr)

    def broken_enhance(m, state, audio_t):
        raise RuntimeError("model exploded")

    out = ingest._denoise_window(window, sr, object(), df_state, broken_enhance)
    assert np.array_equal(out, window)
