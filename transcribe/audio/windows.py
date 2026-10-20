"""Speech windowing — audio in, decodable windows out.

The concept the codebase had no name for: turning a raw audio array into time
ranges a model can actually decode. Three steps that only make sense together —

1. Silero VAD span detection with **no** max-duration cap.
2. The zero-gap span merge (2026-08-06 dropped-content incident fix).
3. Splitting an over-long span into sub-windows under the decoder's limit.

— previously lived as three separately-importable privates inside the
faster-whisper adapter, and `engines/qwen3_asr.py` imported two of the three.
That import walked straight through the Engine Contract, and the two-of-three
is exactly the cost: Qwen3-ASR never got step 2, so the content-loss fix
applied to one engine's path only.

`speech_windows` therefore does all three steps in one call. Exposing them
separately would preserve the defect in a new location.

This module must not import anything from `transcribe/engines/`. It depends on
`faster_whisper.vad` for Silero only — the vendored VAD utility, not the
adapter — so a windowing unit test needs neither a GPU nor a model directory.

**`pipeline/ingest.py` is a related but distinct concern and deliberately does
not sit behind this seam** (investigated for issue #4). Ingest runs a different
Silero — the `silero-vad` pip package, not faster-whisper's vendored copy — at
different settings (threshold 0.5 vs 0.35, min_silence 300ms vs 500ms, plus a
minimum-speech floor this has no equivalent for), then sub-splits each segment
on raw RMS energy, and produces a persisted master timeline of *both* speech and
silence spans (the `speech_span` table, which CutDeck and the editor read)
rather than decodable windows. It also owns denoising and optional chunk
materialization with overlap. Forcing it behind one call would mean changing one
side's detection behaviour, which is a harness-gated probe, not a refactor.
"""

from __future__ import annotations

from dataclasses import dataclass

_SR = 16000


@dataclass(frozen=True)
class Window:
    """One decodable time range.

    Units are explicit on purpose: the pre-extraction code passed bare
    `(start_s, end_s)` float tuples and converted to milliseconds at three
    separate call sites, so a seconds value and a milliseconds value were one
    typo apart. Both accessors are derived from the same seconds field, so they
    cannot disagree.

    `span_index` identifies which detected speech span this window came from.
    Windows sharing a span_index are overlapping pieces of one continuous run of
    speech, which is what a caller needs in order to stitch their decodes back
    together; a span short enough to decode whole yields exactly one window.
    """

    start_s: float
    end_s: float
    span_index: int

    @property
    def start_ms(self) -> int:
        return int(self.start_s * 1000)

    @property
    def end_ms(self) -> int:
        return int(self.end_s * 1000)

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass(frozen=True)
class WindowPolicy:
    """How to turn audio into decodable windows.

    Defaults are faster-whisper's production values. Qwen3-ASR's differ
    deliberately — see `QWEN3_LIKE` below and the test that pins the difference.

    `merge_max_gap_s`: maximum reported inter-span gap to treat as an artifact
    of VAD padding and merge across. **`None` disables merging entirely**, which
    is not the same as `0.0`: a reported gap of exactly `0.0` is the *common*
    case this merge exists to catch (see `_merge_contiguous_spans`), so `0.0`
    would still merge touching spans. `None` is what preserves an engine that
    historically never merged at all.

    `overlap_s`: how much consecutive sub-windows of one over-long span share.
    Overlap only helps a caller that dedupes at the seam; a caller with no
    seam-dedupe pass wants `0.0`, or the overlap duplicates text in its output.
    """

    vad_threshold: float = 0.35
    vad_min_silence_ms: int = 500
    merge_max_gap_s: float | None = 0.05
    max_span_s: float = 25.0
    overlap_s: float = 4.0
    whole_clip_on_silence: bool = False
    speech_pad_ms: int = 400


def _extract_span_range(s) -> tuple[float, float] | None:
    if hasattr(s, "start_ms") and hasattr(s, "end_ms"):
        start_ms, end_ms = s.start_ms, s.end_ms
    elif isinstance(s, (tuple, list)) and len(s) >= 2:
        start_ms, end_ms = s[0], s[1]
    else:
        return None
    if end_ms <= start_ms:
        return None
    return (float(start_ms) / 1000.0, float(end_ms) / 1000.0)


def _pad_speech_spans(
    spans: list[tuple[float, float]],
    pad_s: float,
    total_dur_s: float,
) -> list[tuple[float, float]]:
    """Pad speech spans by `pad_s`, splitting pauses under 2*pad_s evenly.

    Matches faster_whisper.vad's get_speech_timestamps padding logic:
    - First span padded left by pad_s (clamped at 0.0).
    - Last span padded right by pad_s (clamped at total_dur_s).
    - Between consecutive spans with silence < 2*pad_s: the silence is split
      evenly so the padded spans meet at the midpoint (reported gap 0.0).
    - Between consecutive spans with silence >= 2*pad_s: both sides padded by pad_s.
    """
    n = len(spans)
    if n == 0 or pad_s <= 0:
        return list(spans)

    new_spans: list[tuple[float, float]] = []
    for i in range(n):
        s_i, e_i = spans[i]
        if i == 0:
            s = max(0.0, s_i - pad_s)
        else:
            prev_e = spans[i - 1][1]
            gap = max(0.0, s_i - prev_e)
            s = s_i - (gap / 2.0 if gap < 2 * pad_s else pad_s)
            s = max(0.0, s)

        if i == n - 1:
            e = min(total_dur_s, e_i + pad_s) if total_dur_s > 0 else (e_i + pad_s)
        else:
            next_s = spans[i + 1][0]
            gap = max(0.0, next_s - e_i)
            e = e_i + (gap / 2.0 if gap < 2 * pad_s else pad_s)
            if total_dur_s > 0:
                e = min(total_dur_s, e)
        new_spans.append((s, e))
    return new_spans


def speech_windows(
    audio,
    policy: WindowPolicy | None = None,
    speech_spans: tuple[tuple[int, int], ...] | list[tuple[int, int]] | None = None,
) -> list[Window]:
    """Detect speech in `audio` (16kHz mono float32) and return decodable windows.

    Detection, zero-gap merge and over-long split all happen here; callers do
    not compose them.

    When `speech_spans` is provided (e.g. from ingest), derives padded, merged,
    and split decode windows directly from those spans, avoiding a redundant
    full-file Silero VAD pass. Falls back to `faster_whisper.vad` VAD when
    `speech_spans` is empty or None.

    Returns `[]` when VAD finds no speech and `policy.whole_clip_on_silence` is
    False — the caller then decides what "no speech detected" means for it
    (falling back to the decoder's own VAD, emitting nothing, ...). With the flag
    set, the whole clip is treated as one detected span instead, and is windowed
    like any other.
    """
    policy = policy or WindowPolicy()
    total_dur_s = (len(audio) / _SR) if audio is not None and hasattr(audio, "__len__") and len(audio) > 0 else 0.0

    if speech_spans:
        raw_spans = []
        for item in speech_spans:
            rng = _extract_span_range(item)
            if rng is not None:
                raw_spans.append(rng)
        raw_spans.sort(key=lambda x: (x[0], x[1]))
        merged_raw: list[tuple[float, float]] = []
        for s, e in raw_spans:
            if merged_raw and s <= merged_raw[-1][1]:
                merged_raw[-1] = (merged_raw[-1][0], max(merged_raw[-1][1], e))
            else:
                merged_raw.append((s, e))

        if not merged_raw:
            if not policy.whole_clip_on_silence:
                return []
            spans = [(0.0, total_dur_s)]
        else:
            pad_s = policy.speech_pad_ms / 1000.0
            clip_dur = total_dur_s if total_dur_s > 0 else (merged_raw[-1][1] + pad_s)
            padded = _pad_speech_spans(merged_raw, pad_s, clip_dur)
            if policy.merge_max_gap_s is not None:
                spans = _merge_contiguous_spans(padded, policy.merge_max_gap_s)
            else:
                spans = padded
    else:
        spans = _vad_speech_spans(audio, policy.vad_threshold, policy.vad_min_silence_ms)
        if not spans:
            if not policy.whole_clip_on_silence:
                return []
            spans = [(0.0, total_dur_s)]
        if policy.merge_max_gap_s is not None:
            spans = _merge_contiguous_spans(spans, policy.merge_max_gap_s)

    windows: list[Window] = []
    for span_index, (start_s, end_s) in enumerate(spans):
        for win_start, win_end in _split_long_span(
                start_s, end_s, policy.max_span_s, policy.overlap_s):
            windows.append(Window(win_start, win_end, span_index))
    return windows


def _vad_speech_spans(audio, threshold: float, min_silence_ms: int) -> list[tuple[float, float]]:
    """Real speech spans (in seconds) with NO max-duration cap.

    We deliberately don't use faster-whisper's vad_filter=True path for this —
    its internal VadOptions defaults max_speech_duration_s to the encoder's
    chunk_length and splits long runs "aggressively" at that boundary if no
    silence is nearby. Detecting spans uncapped lets `speech_windows` decide how
    to split anything too long, with overlap, instead of an arbitrary hard cut.
    """
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    opts = VadOptions(threshold=threshold, min_silence_duration_ms=min_silence_ms)
    ts = get_speech_timestamps(audio, opts)
    return [(t["start"] / _SR, t["end"] / _SR) for t in ts]


def _merge_contiguous_spans(spans: list[tuple[float, float]],
                             max_gap_s: float = 0.05) -> list[tuple[float, float]]:
    """Merge adjacent VAD spans separated by a (near-)zero reported gap.

    Root cause of a 2026-08-06 production incident (TODO_LEDGER.md, "recurring
    mid-word truncation / dropped-content bug"): faster_whisper.vad's own
    get_speech_timestamps pads each speech chunk by speech_pad_ms (400ms) on
    both sides, and when the real silence between two consecutive chunks is
    under 2*speech_pad_ms (800ms) it splits that silence evenly onto both
    sides instead — so the *reported* gap between the two returned spans is
    exactly 0 for ANY real pause shorter than ~800ms (a routine breath or
    clause boundary in conversational speech), indistinguishable in the
    output from "no pause at all". Callers used to treat every VAD span as a
    fully independent decode: overlap+stitch only reconciles windows *inside*
    one span, so a zero-gap pair of spans got a hard, unrecovered seam right
    where real speech continued. Confirmed on the real incident audio:
    redecoding straight across one such seam (as a single window) recovered a
    ~4s utterance that was completely missing from production output. Merging
    first means the seam disappears before windowing ever happens, and the
    existing overlap+stitch + tail-recovery machinery covers it like any other
    internal boundary. A genuine pause (>=~800ms real silence) still reports a
    nonzero gap here and is left as a separate span, unchanged.
    """
    if not spans:
        return spans
    merged = [spans[0]]
    for start, end in spans[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end <= max_gap_s:
            merged[-1] = (prev_start, end)
        else:
            merged.append((start, end))
    return merged


def _split_long_span(start_s: float, end_s: float,
                      max_span_s: float, overlap_s: float) -> list[tuple[float, float]]:
    """Chop a speech span longer than max_span_s into overlapping sub-windows,
    each safely under the decoder's context limit. Returns [(start_s, end_s)]
    unchanged if the span is already short enough."""
    if end_s - start_s <= max_span_s:
        return [(start_s, end_s)]
    stride = max_span_s - overlap_s
    windows = []
    pos = start_s
    while True:
        win_end = min(pos + max_span_s, end_s)
        windows.append((pos, win_end))
        if win_end >= end_s:
            break
        pos += stride
    return windows
