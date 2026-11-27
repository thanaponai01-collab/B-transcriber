"""Whole-file audio preparation before VAD and decode: loudness normalisation and speech
enhancement for noisy files only. Both are off unless `audio_prep` in config.yaml sets them.

    audio_prep:
      loudness_target_lufs: -16      # integrated loudness (ITU-R BS.1770) to scale to
      enhance_below_snr_db: 15       # DeepFilterNet only when estimate_snr_db is below this

Enhancement runs before normalisation, and its model is freed before any ASR engine loads.
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

PEAK_CEILING_DB = -1.0


def loudness_normalize(audio: np.ndarray, sr: int, target_lufs: float) -> np.ndarray:
    """Scale to `target_lufs`, but never past a -1 dBFS peak: a quiet file with loud peaks
    stays a little under target rather than clipping."""
    import pyloudnorm
    lufs = pyloudnorm.Meter(sr).integrated_loudness(audio.astype(np.float64))
    if not np.isfinite(lufs):
        return audio
    peak = float(np.max(np.abs(audio))) or 1.0
    gain_db = min(target_lufs - lufs, PEAK_CEILING_DB - 20 * np.log10(peak))
    logger.info("Loudness %.1f LUFS -> gain %+.1f dB (target %.1f)", lufs, gain_db, target_lufs)
    return (audio * np.float32(10 ** (gain_db / 20))).astype(np.float32)


def estimate_snr_db(audio: np.ndarray, sr: int) -> float:
    """Speech level (90th percentile of 10 ms frame levels) minus the noise floor (10th)."""
    hop = max(1, sr // 100)
    n = len(audio) // hop
    if n < 10:
        return float("inf")
    db = 10 * np.log10((audio[:n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-12)
    return float(np.percentile(db, 90) - np.percentile(db, 10))


def _load_deepfilternet():
    import sys
    import types
    if "torchaudio.backend.common" not in sys.modules:
        # df.io imports AudioMetaData only for a type hint; torchaudio 2.9+ removed the module.
        shim = types.ModuleType("torchaudio.backend.common")
        shim.AudioMetaData = object
        sys.modules.setdefault("torchaudio.backend", types.ModuleType("torchaudio.backend"))
        sys.modules["torchaudio.backend.common"] = shim
    from df.enhance import enhance, init_df
    model, state, _ = init_df(log_level="ERROR")
    return model, state, enhance


def enhance(audio: np.ndarray, sr: int) -> np.ndarray:
    import librosa
    import torch
    model, state, run = _load_deepfilternet()
    try:
        x = librosa.resample(audio, orig_sr=sr, target_sr=state.sr())
        with torch.no_grad():
            y = run(model, state, torch.from_numpy(x[None]).float()).cpu().numpy()[0]
        out = librosa.resample(y, orig_sr=state.sr(), target_sr=sr).astype(np.float32)
    finally:
        del model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    return np.pad(out, (0, max(0, len(audio) - len(out))))[:len(audio)]


def prepare(audio: np.ndarray, sr: int, config: dict) -> np.ndarray:
    cfg = config.get("audio_prep") or {}
    below = cfg.get("enhance_below_snr_db")
    if below is not None:
        snr = estimate_snr_db(audio, sr)
        if snr < float(below):
            logger.info("Estimated SNR %.1f dB < %.1f: enhancing", snr, float(below))
            audio = enhance(audio, sr)
    target = cfg.get("loudness_target_lufs")
    if target is not None:
        audio = loudness_normalize(audio, sr, float(target))
    return audio
