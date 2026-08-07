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


# Cue-timing conform (see conform_cues). A gap this short between consecutive
# cues is not a real pause — it is timestamp noise, and it makes burned-in
# subtitles flicker off and back on. Hand-cut reference SRTs are gapless.
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
    * ``0 <= start_ms < end_ms`` (and ``<= duration_ms`` when given)
    * **no two cues overlap** — an overlapping cue's start is pushed to the
      previous cue's end
    * when ``max_close_gap_ms > 0``, any gap that small is closed by extending
      the earlier cue, so the output is gapless like a hand-cut SRT

    This lives outside ``forced_align`` on purpose. The pipeline skips forced
    alignment entirely whenever the engine reports ``timestamps_final`` (which
    faster-whisper always does), so an invariant enforced only inside the
    aligner is an invariant enforced on no active path — that is how an
    overlapping cue pair reached an exported SRT. Call this unconditionally.

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
        # A zero/negative-length cue never renders; give it a single ms. This can
        # push past `ceiling` only when the whole cue sits at the very end.
        end = max(end, start + 1)

        tok.start_ms, tok.end_ms = start, end
        prev_end = end

    if max_close_gap_ms > 0:
        for earlier, later in zip(tokens, tokens[1:]):
            gap = later.start_ms - earlier.end_ms
            if 0 < gap <= max_close_gap_ms:
                earlier.end_ms = later.start_ms
                report["gaps_closed"] += 1

    # Sorting may have moved tokens; idx is positional for every consumer that
    # has one (same contract as normalize.drop_tokens_over_silence).
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
    Returns tokens with monotonic, audio-bounded timestamps.
    """
    if aligner is None:
        aligner = CTCForcedAligner()

    tokens = aligner.align(audio, sr, words)
    # Word-level output: clamp and de-overlap only. Gaps between words are real
    # (they are the pauses), so gap-closing stays off here — it is a cue policy.
    conform_cues(tokens, max_close_gap_ms=0, duration_ms=int(len(audio) * 1000 / sr))
    return tokens


def _quantize_ms(ms: int, fps: float) -> int:
    """Round a millisecond timestamp to the nearest frame boundary at fps."""
    frame_ms = 1000.0 / fps
    return round(round(ms / frame_ms) * frame_ms)


def _quantize_tokens(tokens: list[dict], fps: float) -> list[dict]:
    """Snap start/end timestamps to frame boundaries.

    Editors (e.g. Premiere) round millisecond timecodes to the sequence's
    own frame boundaries on import; if that rounding happens per-cue at
    import time instead of once here, cue starts drift off the intended
    frame, which is what forces the manual recut. Quantizing here makes
    the boundary the editor will show explicit and reproducible.
    """
    frame_ms = 1000.0 / fps
    out = []
    for tok in tokens:
        start = _quantize_ms(tok["start_ms"], fps)
        end = _quantize_ms(tok["end_ms"], fps)
        if end <= start:
            end = start + round(frame_ms)
        out.append({**tok, "start_ms": start, "end_ms": end})
    return out


def export_srt(tokens: list[dict], path: str, fps: float | None = None) -> None:
    """Export token list (dicts with text/start_ms/end_ms) to SRT.

    fps: if given, quantizes cue boundaries to the target sequence's frame
    rate before formatting (varies per clip, so must be passed per call).
    """
    if fps:
        tokens = _quantize_tokens(tokens, fps)

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


def export_vtt(tokens: list[dict], path: str, fps: float | None = None) -> None:
    """Export token list to WebVTT.

    fps: if given, quantizes cue boundaries to the target sequence's frame
    rate before formatting (varies per clip, so must be passed per call).
    """
    if fps:
        tokens = _quantize_tokens(tokens, fps)

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
