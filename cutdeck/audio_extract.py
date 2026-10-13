"""Build a timeline-aligned mono mixdown from a typed sequence and original source media.

Gain, EQ, panning and crossfades are not rendered. Reference-track selection belongs
to sequence_model; positions and source In/Out use exact Premiere ticks.
"""
from __future__ import annotations

import shutil
from fractions import Fraction

from cutdeck.sequence_model import Sequence
from cutdeck.sync import extract_mono_audio
from cutdeck.sequence_timing import PPRO_TICKS_PER_SECOND, range_window_frames

_WORKING_SAMPLE_RATE = 48000  # arbitrary but consistent; ingest() resamples to 16k anyway


def extract_mixdown(sequence: Sequence, out_wav: str, audio_track_index: int | None = None,
                    range_start_frame: int | None = None, range_end_frame: int | None = None,
                    pad_seconds: float = 2.0, sample_rate: int = _WORKING_SAMPLE_RATE) -> str:
    """Build a sequence-timeline mono WAV from the sequence's own clips +
    source media, writing it to ``out_wav``. Returns ``out_wav``.

    ``audio_track_index`` (0-based): which Premiere audio track to use as the
    reference dialogue track. Defaults to the first switched-on track that has
    any clips. Disabled clips are skipped — silence, same as they'd be muted
    in a real Premiere render.

    ``range_start_frame``/``range_end_frame`` (sequence frames, both or neither):
    the WAV covers only ``range_window_frames(...)`` = the range plus
    ``pad_seconds`` each side, so ingest/ASR never touch the rest of the
    sequence. Its first sample is the window's first frame: callers shift
    results by that window start to get back to sequence time.
    """
    if (range_start_frame is None) != (range_end_frame is None):
        raise ValueError("range_start_frame and range_end_frame must be given together")
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH — required to extract audio segments")

    tb = sequence.timebase
    seq_frames = sequence.duration_frames
    lo_f, hi_f = (0, seq_frames)
    if range_start_frame is not None:
        lo_f, hi_f = range_window_frames(tb, seq_frames, (range_start_frame, range_end_frame),
                                         pad_seconds)
    win_lo_s = float(Fraction(lo_f * tb.fps_den, tb.fps_num))
    win_hi_s = float(Fraction(hi_f * tb.fps_den, tb.fps_num))
    total_samples = int(round((win_hi_s - win_lo_s) * sample_rate))

    track = sequence.reference_track(audio_track_index)

    window = (win_lo_s, win_hi_s) if range_start_frame is not None else None

    import numpy as np
    import soundfile as sf

    buffer = np.zeros(total_samples, dtype=np.float32)
    for clip in track.clips:
        if not clip.enabled:
            continue
        src_path = clip.media_path
        in_s = clip.in_ticks / PPRO_TICKS_PER_SECOND
        out_s = clip.out_ticks / PPRO_TICKS_PER_SECOND
        start_s = clip.start_ticks / PPRO_TICKS_PER_SECOND
        if window is not None:
            # Trim the source span to the part of the clip inside the window.
            keep_lo = max(start_s, window[0])
            keep_hi = min(start_s + (out_s - in_s), window[1])
            if keep_hi <= keep_lo:
                continue
            in_s, out_s = in_s + (keep_lo - start_s), in_s + (keep_hi - start_s)
            start_s = keep_lo

        seg_audio = extract_mono_audio(src_path, start_s=in_s, duration_s=out_s - in_s,
                                       sample_rate=sample_rate)
        offset = int(round((start_s - win_lo_s) * sample_rate))
        end = min(offset + len(seg_audio), total_samples)
        if end > offset:
            buffer[offset:end] = seg_audio[: end - offset]

    sf.write(out_wav, buffer, sample_rate)
    return out_wav
