"""Window-decode-stitch composition — issue #13.

`windows.py` decides how much consecutive decode windows of an over-long span
share (`WindowPolicy.overlap_s`); `stitch.py` removes the duplicate words that
sharing produces. Nothing bound the two together before this module existed —
a caller could set an overlap and forget the seam-dedupe pass (or the reverse),
and the invariant only held because a docstring said so, from the other side of
the Engine Contract (`transcribe/pipeline/stitch.py`, where `stitch` used to
live). `decode_windows` is the one call that ties them together: decode each
window, offset its local timestamps to the global timeline, and stitch the
seams — so a caller cannot get one half without the other.

Both current callers do this same four-step shape by hand: `faster_whisper.py`
decodes an over-long pause-free VAD span as several overlapping sub-windows
(`transcribe.audio.windows.Window`, sliced with its own audio and wrapped as
`AudioWindow` below); `pipeline/engine_run.py` decodes ingest-materialised
chunks that overlap by `chunk_overlap_ms` (`pipeline.ingest.AudioChunk`). They
differ in where their windows come from — one splits one continuous span per
`WindowPolicy`, the other receives chunks ingest already built with its own,
unrelated overlap policy (see `windows.py`'s module docstring on why the two
detection paths are not unified) — so this module does not decide how windows
are produced or import `WindowPolicy` itself; it only requires each window
expose `.audio` (that window's own raw audio slice), `.start_ms` and `.end_ms`
(its place on the global timeline). `AudioChunk` already has exactly that
shape. The overlap value that produced the windows (`policy.overlap_s * 1000`,
or `chunk_overlap_ms`) is passed in as `seam_window_ms` rather than a
`WindowPolicy` object, since a chunk-engine caller has no `WindowPolicy` to
offer — only the loop is shared between the two callers, not the numbers
behind it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, Sequence

from transcribe.audio.stitch import ChunkTokens, stitch
from transcribe.contracts import RecognizedToken


class _AudioWindow(Protocol):
    """Anything with these three attributes works as a `decode_windows` input
    — duck-typed so `pipeline.ingest.AudioChunk` needs no adapter."""

    audio: object
    start_ms: int
    end_ms: int


@dataclass
class AudioWindow:
    """A decode window: this window's own audio slice plus its global span.

    For callers (like `faster_whisper.py`) whose windows come from
    `transcribe.audio.windows.Window`, which carries a time range but not
    audio — wrap the sliced audio with the window's own `start_ms`/`end_ms`.
    """

    audio: object
    start_ms: int
    end_ms: int


def decode_windows(windows: Sequence[_AudioWindow],
                    decode_fn: Callable[[object], list[RecognizedToken]],
                    seam_window_ms: int) -> list[RecognizedToken]:
    """Decode each of `windows` through `decode_fn`, offset local timestamps to
    global, and stitch overlapping seams into one token stream.

    `decode_fn(window.audio) -> list[RecognizedToken]` decodes ONE window and
    returns its tokens with window-LOCAL millisecond timestamps; this call
    offsets them to the window's own `start_ms` before stitching. Windows are
    decoded in the given order — a caller whose decode already happened in one
    batched call (e.g. `engine.transcribe_batch`) can hand back pre-computed
    per-window results through `decode_fn` just as well as a caller that
    decodes one window at a time.

    Pass the overlap that produced these windows (e.g.
    `int(WindowPolicy.overlap_s * 1000)`, or ingest's `chunk_overlap_ms`) as
    `seam_window_ms`, so the seam search covers exactly the zone a word can
    legitimately appear twice — see `stitch`'s docstring.
    """
    chunks: list[ChunkTokens] = []
    for w in windows:
        local_tokens = decode_fn(w.audio)
        for t in local_tokens:
            t.start_ms += w.start_ms
            t.end_ms += w.start_ms
        chunks.append(ChunkTokens(local_tokens, w.start_ms, w.end_ms))
    return stitch(chunks, seam_window_ms=seam_window_ms)
