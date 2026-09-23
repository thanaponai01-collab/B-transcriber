"""cutdeck.sync — audio waveform cross-correlation engine for multi-camera sync.

Provides fast, sub-frame acoustic alignment between camera scratch audio and a
reference audio track using GCC-PHAT (Generalized Cross-Correlation with Phase Transform)
and Peak-to-Sidelobe Ratio (PSR) confidence scoring.

Pure mathematical/signal processing — no GUI or Premiere dependencies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
import shutil
import subprocess
from typing import Optional

import numpy as np

from cutdeck.contracts import Timebase

logger = logging.getLogger(__name__)

# Default audio sampling rate for alignment. 16kHz captures speech formants up to 8kHz,
# providing ~0.0625ms temporal resolution (over 500x finer than a 30fps video frame).
DEFAULT_SAMPLE_RATE = 16000

# Minimum Peak-to-Sidelobe Ratio (PSR) to consider a correlation peak trustworthy.
# Synthetic and empirical tests show true speech matches exhibit PSR > 15-50+,
# while random noise / unrelated audio stays below 6-8.
DEFAULT_MIN_PSR = 10.0

# Minimum root-mean-square amplitude for a clip to be considered non-silent.
DEFAULT_MIN_RMS = 1e-4

# Minimum clip duration in seconds to attempt alignment.
DEFAULT_MIN_DURATION_S = 0.5


@dataclass(frozen=True)
class SyncResult:
    """Result of aligning a target audio clip against a reference timeline."""
    is_synced: bool
    offset_ms: float
    offset_frames: int
    confidence: float
    reason: str  # 'matched' | 'silent' | 'too_short' | 'low_confidence' | 'error'


def extract_mono_audio(
    media_path: Path | str,
    *,
    start_s: Optional[float] = None,
    duration_s: Optional[float] = None,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> np.ndarray:
    """Extract mono float32 audio directly into a numpy array via ffmpeg stdout pipe.

    Reads raw IEEE 754 32-bit little-endian floats (f32le) directly from pipe:1 with
    zero intermediate disk I/O.
    """
    path_obj = Path(media_path)
    if not path_obj.exists():
        raise FileNotFoundError(f"Media file not found: {media_path}")

    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH — required for audio extraction")

    cmd = ["ffmpeg", "-nostdin", "-y"]
    if start_s is not None and start_s > 0:
        cmd.extend(["-ss", f"{start_s:.6f}"])
    cmd.extend(["-i", str(path_obj)])
    if duration_s is not None and duration_s > 0:
        cmd.extend(["-t", f"{duration_s:.6f}"])
    cmd.extend([
        "-vn",
        "-ac", "1",
        "-ar", str(sample_rate),
        "-f", "f32le",
        "pipe:1",
    ])

    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        err_msg = proc.stderr.decode("utf-8", errors="replace")[-500:]
        raise RuntimeError(f"ffmpeg extraction failed for {media_path}: {err_msg}")

    return np.frombuffer(proc.stdout, dtype=np.float32)


def correlate_gcc_phat(
    ref_audio: np.ndarray,
    clip_audio: np.ndarray,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> tuple[float, float]:
    """Compute time delay between reference and clip audio using GCC-PHAT.

    Returns:
        (offset_s, psr):
            offset_s: Time in seconds that clip starts relative to reference start.
                      Positive: clip starts AFTER reference start.
                      Negative: clip starts BEFORE reference start.
            psr: Peak-to-Sidelobe Ratio (confidence score).
    """
    offset_s, psr, _ = correlate_gcc_phat_detail(ref_audio, clip_audio, sample_rate)
    return offset_s, psr


def correlate_gcc_phat_detail(
    ref_audio: np.ndarray,
    clip_audio: np.ndarray,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> tuple[float, float, float]:
    """`correlate_gcc_phat`, plus how close the runner-up match came.

    Returns (offset_s, psr, runner_up): runner_up is the highest correlation outside the
    +/-50 ms peak window divided by the peak (0..1). Near 1.0 means two places match about
    equally well — repeated sound, a music loop — so the offset is not trustworthy however
    high the PSR is.
    """
    if len(ref_audio) == 0 or len(clip_audio) == 0:
        return 0.0, 0.0, 0.0

    n_ref = len(ref_audio)
    n_clip = len(clip_audio)
    n_total = n_ref + n_clip

    # Next power of 2 for fast FFT
    n_fft = int(2 ** np.ceil(np.log2(n_total)))

    # Compute FFT
    X_ref = np.fft.rfft(ref_audio, n_fft)
    X_clip = np.fft.rfft(clip_audio, n_fft)

    # Cross-power spectrum
    R = X_ref * np.conj(X_clip)

    # Phase Transform (whitening)
    R_phat = R / (np.abs(R) + 1e-12)

    # Inverse FFT to get generalized cross-correlation
    cc = np.fft.irfft(R_phat, n_fft)

    # Peak detection
    peak_idx = int(np.argmax(cc))
    peak_val = float(cc[peak_idx])

    # Convert circular FFT index to linear lag
    # Index 0 .. n_ref-1: positive lags (clip starts after ref)
    # Index n_fft - n_clip + 1 .. n_fft - 1: negative lags (clip starts before ref)
    # Split at n_ref, not n_fft // 2: positive lags reach n_ref - 1, which is past the midpoint
    # whenever n_ref + n_clip sits just under a power of two (a clip starting late was read as
    # a large negative offset; regression test in tests/test_cutdeck_sync_audio.py).
    if peak_idx >= n_ref:
        lag_samples = peak_idx - n_fft
    else:
        lag_samples = peak_idx

    offset_s = lag_samples / sample_rate

    # Calculate Peak-to-Sidelobe Ratio (PSR)
    # Mask out a +/- 50ms window around peak
    win_samples = int(0.05 * sample_rate)
    mask = np.ones(len(cc), dtype=bool)
    start_mask = max(0, peak_idx - win_samples)
    end_mask = min(len(cc), peak_idx + win_samples + 1)
    mask[start_mask:end_mask] = False

    # Also mask wrap-around edges if peak is near boundary
    if peak_idx < win_samples:
        mask[len(cc) - (win_samples - peak_idx):] = False
    elif peak_idx > len(cc) - win_samples:
        mask[:win_samples - (len(cc) - peak_idx)] = False

    sidelobes = cc[mask]
    if len(sidelobes) > 0:
        mean_sidelobe = float(np.mean(sidelobes))
        std_sidelobe = float(np.std(sidelobes))
        psr = (peak_val - mean_sidelobe) / (std_sidelobe + 1e-12)
        runner_up = float(np.max(sidelobes)) / peak_val if peak_val > 0 else 1.0
    else:
        psr = 0.0
        runner_up = 1.0

    return offset_s, max(0.0, psr), max(0.0, runner_up)


def sync_clip_to_reference(
    ref_audio: np.ndarray,
    clip_audio: np.ndarray,
    tb: Timebase,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    min_psr: float = DEFAULT_MIN_PSR,
    min_rms: float = DEFAULT_MIN_RMS,
    min_duration_s: float = DEFAULT_MIN_DURATION_S,
) -> SyncResult:
    """Align a single audio clip against a reference audio stream.

    Determines whether the clip matches with sufficient confidence, computing
    frame-exact offsets using the provided sequence Timebase.
    """
    duration_s = len(clip_audio) / sample_rate
    if duration_s < min_duration_s:
        return SyncResult(
            is_synced=False,
            offset_ms=0.0,
            offset_frames=0,
            confidence=0.0,
            reason="too_short",
        )

    rms = float(np.sqrt(np.mean(clip_audio ** 2)))
    if rms < min_rms:
        return SyncResult(
            is_synced=False,
            offset_ms=0.0,
            offset_frames=0,
            confidence=0.0,
            reason="silent",
        )

    try:
        offset_s, psr = correlate_gcc_phat(ref_audio, clip_audio, sample_rate)
    except Exception as exc:
        logger.warning(f"Correlation error: {exc}")
        return SyncResult(
            is_synced=False,
            offset_ms=0.0,
            offset_frames=0,
            confidence=0.0,
            reason=f"error: {exc}",
        )

    # Convert offset to exact frames using sequence rational timebase
    offset_frames = round(offset_s * tb.fps_num / tb.fps_den)
    offset_ms = float(Fraction(offset_frames * tb.fps_den * 1000, tb.fps_num))

    if psr < min_psr:
        return SyncResult(
            is_synced=False,
            offset_ms=offset_ms,
            offset_frames=offset_frames,
            confidence=psr,
            reason="low_confidence",
        )

    return SyncResult(
        is_synced=True,
        offset_ms=offset_ms,
        offset_frames=offset_frames,
        confidence=psr,
        reason="matched",
    )
