"""Recording-condition robustness: the gold clips re-run under gain shifts, noise and a music bed.

Each gold clip is decoded once per `Condition`. `cer_thai_spread` is the largest minus the smallest
corpus `cer_thai` across conditions (the clean condition included), so a pipeline whose accuracy
does not depend on how the audio was recorded scores near 0. Resampling for its confidence band
draws whole gold clips, keeping every condition of a clip together.

+6 dB clips at full scale, as a hot recording would. Noise and music are scaled against the clip's
active-speech level (`_active_rms`), not its whole-file RMS, so long pauses don't lower the bed.
"""
from __future__ import annotations

import random
from typing import NamedTuple

import numpy as np

from transcribe.eval.metrics import CI_METRICS, EvalMetrics


class Condition(NamedTuple):
    name: str
    gain_db: float = 0.0
    noise_snr_db: float | None = None
    music_snr_db: float | None = None


CONDITIONS = (
    Condition("clean"),
    Condition("gain-18", gain_db=-18.0),
    Condition("gain-12", gain_db=-12.0),
    Condition("gain-6", gain_db=-6.0),
    Condition("gain+6", gain_db=6.0),
    Condition("noise10", noise_snr_db=10.0),
    Condition("music10", music_snr_db=10.0),
)

_NOISE_SEED = 20261127


def _active_rms(audio: np.ndarray, sr: int, window_db: float = 30.0) -> float:
    hop = max(1, sr // 100)
    n = len(audio) // hop
    if n == 0:
        return float(np.sqrt(np.mean(audio ** 2))) if len(audio) else 0.0
    power = (audio[:n * hop].reshape(n, hop) ** 2).mean(axis=1)
    db = 10 * np.log10(power + 1e-12)
    active = power[db >= db.max() - window_db]
    return float(np.sqrt(active.mean()))


def pink_noise(n: int, seed: int = _NOISE_SEED) -> np.ndarray:
    spectrum = np.fft.rfft(np.random.default_rng(seed).standard_normal(n))
    freqs = np.arange(len(spectrum), dtype=np.float64)
    freqs[0] = 1.0
    noise = np.fft.irfft(spectrum / np.sqrt(freqs), n)
    return (noise / (np.sqrt(np.mean(noise ** 2)) + 1e-12)).astype(np.float32)


def _bed_at_snr(audio: np.ndarray, sr: int, bed: np.ndarray, snr_db: float) -> np.ndarray:
    bed = np.resize(bed, len(audio)).astype(np.float32)
    bed_rms = float(np.sqrt(np.mean(bed ** 2))) + 1e-12
    return bed * (_active_rms(audio, sr) / bed_rms) * 10 ** (-snr_db / 20)


def perturb(audio: np.ndarray, sr: int, condition: Condition,
            music: np.ndarray | None = None) -> np.ndarray:
    out = audio.astype(np.float32)
    if condition.noise_snr_db is not None:
        out = out + _bed_at_snr(audio, sr, pink_noise(len(audio)), condition.noise_snr_db)
    if condition.music_snr_db is not None:
        if music is None:
            raise ValueError(f"condition {condition.name} needs a music bed (eval_robustness.music_bed)")
        out = out + _bed_at_snr(audio, sr, music, condition.music_snr_db)
    out = out * np.float32(10 ** (condition.gain_db / 20))
    return np.clip(out, -1.0, 1.0)


def condition_cer(by_condition: dict[str, list[EvalMetrics]]) -> dict[str, float]:
    return {name: EvalMetrics.aggregate(clips).cer_thai for name, clips in by_condition.items()}


def cer_thai_spread(by_condition: dict[str, list[EvalMetrics]]) -> float:
    rates = condition_cer(by_condition).values()
    return max(rates) - min(rates) if rates else 0.0


ROBUST_METRICS = CI_METRICS + ("cer_thai_spread",)


def _statistic(by_condition: dict[str, list[EvalMetrics]], indices: list[int], metric: str) -> float:
    picked = {name: [clips[i] for i in indices] for name, clips in by_condition.items()}
    if metric == "cer_thai_spread":
        return cer_thai_spread(picked)
    return getattr(EvalMetrics.aggregate([m for clips in picked.values() for m in clips]), metric)


def pooled(by_condition: dict[str, list[EvalMetrics]]) -> EvalMetrics:
    return EvalMetrics.aggregate([m for clips in by_condition.values() for m in clips])


def _draws(n: int, n_draws: int, seed: int | None):
    rng = random.Random(seed)
    for _ in range(n_draws):
        yield [rng.randrange(n) for _ in range(n)]


def _band(values: list[float], ci: float) -> tuple[float, float]:
    values = sorted(values)
    return (values[int((1 - ci) / 2 * len(values))],
            values[min(len(values) - 1, int((1 + ci) / 2 * len(values)))])


def bootstrap_ci(by_condition: dict[str, list[EvalMetrics]], metric: str,
                 n_draws: int = 1000, ci: float = 0.95, seed: int | None = 0) -> tuple[float, float]:
    n = len(next(iter(by_condition.values())))
    return _band([_statistic(by_condition, idx, metric) for idx in _draws(n, n_draws, seed)], ci)


def paired_bootstrap_ci(candidate: dict[str, list[EvalMetrics]], baseline: dict[str, list[EvalMetrics]],
                        metric: str, n_draws: int = 1000, ci: float = 0.95,
                        seed: int | None = 0) -> tuple[float, float]:
    """Candidate minus baseline; both dicts hold the same conditions with clips in the same order."""
    if candidate.keys() != baseline.keys():
        raise ValueError("paired robustness runs need the same conditions")
    n = len(next(iter(candidate.values())))
    return _band([_statistic(candidate, idx, metric) - _statistic(baseline, idx, metric)
                  for idx in _draws(n, n_draws, seed)], ci)
