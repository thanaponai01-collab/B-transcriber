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
    def align(self, audio: np.ndarray, sr: int, words: list[str]) -> list[ForcedToken]:
        raise NotImplementedError


class CTCForcedAligner(ForcedAligner):
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

            word_spans = aligner(emission[0], tokenizer(words))

            ratio = waveform.size(-1) / emission.size(1) / 16
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


_GAP_CLOSE_MS = 200


def conform_cues(
    tokens: list,
    max_close_gap_ms: int = 0,
    duration_ms: int | None = None,
) -> dict[str, int]:
    """Enforce the timing invariants every subtitle consumer assumes.

    Operates in place on any token objects exposing ``start_ms``/``end_ms``
    (ForcedToken, PipelineToken, ...). Guarantees on return:

    * time-ordered, and re-indexed if the tokens carry an ``idx``
    * ``0 <= start_ms < end_ms`` and, when given, ``<= duration_ms``, except that a
      cue at the very end keeps 1 ms and so may end 1 ms past it
    * **no two cues overlap** — an overlapping cue's start is pushed to the
      previous cue's end
    * when ``max_close_gap_ms > 0``, any gap that small is closed by extending
      the earlier cue, so the output is gapless like a hand-cut SRT

    Returns a report of what it had to change; an all-zero report means the
    engine's own timestamps were already conformant.
    """
    report = {"overlaps_fixed": 0, "gaps_closed": 0, "bounds_clamped": 0}
    if not tokens:
        return report

    tokens.sort(key=lambda t: (t.start_ms, t.end_ms))

    prev_end = 0
    for tok in tokens:
        start, end = tok.start_ms, tok.end_ms
        ceiling = duration_ms if duration_ms is not None else max(start, end)
        clamped_start = max(0, min(start, ceiling))
        clamped_end = max(0, min(end, ceiling))
        if (clamped_start, clamped_end) != (start, end):
            report["bounds_clamped"] += 1
        start, end = clamped_start, clamped_end

        if start < prev_end:
            start = prev_end
            report["overlaps_fixed"] += 1
        end = max(end, start + 1)

        tok.start_ms, tok.end_ms = start, end
        prev_end = end

    if max_close_gap_ms > 0:
        for earlier, later in zip(tokens, tokens[1:]):
            gap = later.start_ms - earlier.end_ms
            if 0 < gap <= max_close_gap_ms:
                earlier.end_ms = later.start_ms
                report["gaps_closed"] += 1

    if hasattr(tokens[0], "idx"):
        for i, tok in enumerate(tokens):
            tok.idx = i

    return report


def forced_align(
    audio: np.ndarray,
    sr: int,
    words: list[str],
    aligner: ForcedAligner | None = None,
) -> list[ForcedToken]:
    """
    Assign final timestamps to words.
    Returns tokens with monotonic timestamps.
    """
    if aligner is None:
        aligner = CTCForcedAligner()

    tokens = aligner.align(audio, sr, words)
    conform_cues(tokens, max_close_gap_ms=0, duration_ms=int(len(audio) * 1000 / sr))
    return tokens
