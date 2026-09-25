"""xml_audio_extract.py — build a sequence-timeline mixdown WAV directly from
an exported FCP7 XML's own clipitems and source media, no Premiere render.

``sequence_mixdown.py``'s ingest path needs a waveform that represents what
the editor actually hears across the sequence's timeline, to run VAD/silence
detection against. Normally that means the editor exports one by hand
(``File > Export > Media``). This module builds the same kind of waveform
without that step: the XML already names every source file and its exact
in/out/start/end on the timeline, so each audio clip's segment can be pulled
straight from its original source file (via ffmpeg) and pasted into a silence
buffer at its timeline position — the same pattern the retired mark-and-apply
``live_clip.py`` used (reads original media directly rather than waiting on
a render).

**What this trades away, on purpose:** a real Premiere export bakes in
whatever the sequence's mix actually does — gain automation, EQ, panning,
crossfades. This module reads only each clip's position and source In/Out (Premiere ticks)
and does none of that. For a plain stacked-clip sequence with no effects
(this project's real sequences, per ``docs/HANDOFF_CUTDECK_XML_RECUT.md``'s
Phase 0 note) that gap is negligible; for a heavily mixed sequence it would
not be — pick the manual export path there instead.

Which track is the "reference" dialogue track is decided by
``cutdeck.sequence_model.Sequence.reference_track`` — the same rule the helper's
pre-ASR check uses.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

from cutdeck.sequence_model import Sequence
from cutdeck.xml_sequence import PPRO_TICKS_PER_SECOND, range_window_frames

_WORKING_SAMPLE_RATE = 48000  # arbitrary but consistent; ingest() resamples to 16k anyway


def extract_mixdown(sequence: Sequence, out_wav: str, audio_track_index: int | None = None,
                    range_start_frame: int | None = None, range_end_frame: int | None = None,
                    pad_seconds: float = 2.0) -> str:
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
    total_samples = int(round((win_hi_s - win_lo_s) * _WORKING_SAMPLE_RATE))

    track = sequence.reference_track(audio_track_index)

    window = (win_lo_s, win_hi_s) if range_start_frame is not None else None

    import numpy as np
    import soundfile as sf

    buffer = np.zeros(total_samples, dtype=np.float32)
    tmp_dir = Path(tempfile.mkdtemp(prefix="cutdeck_extract_"))
    try:
        for i, clip in enumerate(track.clips):
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

            seg_path = tmp_dir / f"seg{i}.wav"
            cmd = ["ffmpeg", "-y", "-i", str(src_path),
                   "-ss", f"{in_s:.9f}", "-to", f"{out_s:.9f}",
                   "-vn", "-ac", "1", "-ar", str(_WORKING_SAMPLE_RATE), str(seg_path)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(
                    f"ffmpeg failed extracting {src_path} [{in_s:.3f}s-{out_s:.3f}s]: "
                    f"{result.stderr[-500:]}"
                )

            seg_audio, _sr = sf.read(str(seg_path), dtype="float32")
            offset = int(round((start_s - win_lo_s) * _WORKING_SAMPLE_RATE))
            end = min(offset + len(seg_audio), total_samples)
            if end > offset:
                buffer[offset:end] = seg_audio[: end - offset]
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    sf.write(out_wav, buffer, _WORKING_SAMPLE_RATE)
    return out_wav
