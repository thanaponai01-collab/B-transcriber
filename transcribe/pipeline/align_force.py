"""Phase 7 — Forced alignment: assign final per-token timestamps.

Uses a code-switch-capable forced aligner. The aligner is wrapped behind a small
interface so it is swappable without touching pipeline code.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ForcedToken:
    text: str
    start_ms: int
    end_ms: int


class ForcedAligner:
    """Base interface for forced aligners. Subclass to swap implementations."""

    def align(self, audio: np.ndarray, sr: int, words: list[str]) -> list[ForcedToken]:
        raise NotImplementedError


class CTCForcedAligner(ForcedAligner):
    """
    Forced aligner using torchaudio CTC approach (wav2vec2-based).
    Handles multilingual / code-switch by working at the character level.
    """

    def __init__(self, device: str = "cuda"):
        self._device = device

    def align(self, audio: np.ndarray, sr: int, words: list[str]) -> list[ForcedToken]:
        try:
            import torch
            import torchaudio

            waveform = torch.from_numpy(audio).unsqueeze(0)
            if sr != 16000:
                waveform = torchaudio.functional.resample(waveform, sr, 16000)

            bundle = torchaudio.pipelines.MMS_FA
            model = bundle.get_model().to(self._device)
            tokenizer = bundle.get_tokenizer()
            aligner = bundle.get_aligner()

            with torch.inference_mode():
                emission, _ = model(waveform.to(self._device))

            # MMS_FA handles multilingual; use it as-is
            word_spans = aligner(emission[0], tokenizer(words))

            ratio = waveform.size(-1) / emission.size(1) / 16  # ms per frame
            tokens = []
            for word, span in zip(words, word_spans):
                start_ms = int(span[0].start * ratio)
                end_ms = int(span[-1].end * ratio)
                tokens.append(ForcedToken(text=word, start_ms=start_ms, end_ms=end_ms))
            return tokens

        except Exception as e:
            logger.warning("CTCForcedAligner failed (%s), falling back to linear interpolation", e)
            return _linear_fallback(words, int(len(audio) * 1000 / sr))


class LinearFallbackAligner(ForcedAligner):
    """Distributes tokens evenly across the audio duration. Used when no aligner available."""

    def align(self, audio: np.ndarray, sr: int, words: list[str]) -> list[ForcedToken]:
        duration_ms = int(len(audio) * 1000 / sr)
        return _linear_fallback(words, duration_ms)


def _linear_fallback(words: list[str], duration_ms: int) -> list[ForcedToken]:
    if not words:
        return []
    step = duration_ms // len(words)
    tokens = []
    for i, word in enumerate(words):
        tokens.append(ForcedToken(
            text=word,
            start_ms=i * step,
            end_ms=(i + 1) * step,
        ))
    return tokens


def forced_align(
    audio: np.ndarray,
    sr: int,
    words: list[str],
    aligner: ForcedAligner | None = None,
) -> list[ForcedToken]:
    """
    Assign final timestamps to words.
    Returns tokens with monotonic, audio-bounded timestamps.
    """
    if aligner is None:
        aligner = CTCForcedAligner()

    tokens = aligner.align(audio, sr, words)
    duration_ms = int(len(audio) * 1000 / sr)

    # Validate: monotonic and within bounds
    prev_end = 0
    for tok in tokens:
        tok.start_ms = max(0, min(tok.start_ms, duration_ms))
        tok.end_ms = max(tok.start_ms + 1, min(tok.end_ms, duration_ms))
        if tok.start_ms < prev_end:
            tok.start_ms = prev_end
            tok.end_ms = max(tok.start_ms + 1, tok.end_ms)
        prev_end = tok.end_ms

    return tokens


def export_srt(tokens: list[dict], path: str) -> None:
    """Export token list (dicts with text/start_ms/end_ms) to SRT."""

    def ms_to_srt(ms: int) -> str:
        h = ms // 3_600_000
        m = (ms % 3_600_000) // 60_000
        s = (ms % 60_000) // 1000
        ms_rem = ms % 1000
        return f"{h:02d}:{m:02d}:{s:02d},{ms_rem:03d}"

    lines = []
    for i, tok in enumerate(tokens, 1):
        lines.append(str(i))
        lines.append(f"{ms_to_srt(tok['start_ms'])} --> {ms_to_srt(tok['end_ms'])}")
        lines.append(tok["text"])
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def export_vtt(tokens: list[dict], path: str) -> None:
    """Export token list to WebVTT."""

    def ms_to_vtt(ms: int) -> str:
        h = ms // 3_600_000
        m = (ms % 3_600_000) // 60_000
        s = (ms % 60_000) // 1000
        ms_rem = ms % 1000
        return f"{h:02d}:{m:02d}:{s:02d}.{ms_rem:03d}"

    lines = ["WEBVTT", ""]
    for tok in tokens:
        lines.append(f"{ms_to_vtt(tok['start_ms'])} --> {ms_to_vtt(tok['end_ms'])}")
        lines.append(tok["text"])
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
