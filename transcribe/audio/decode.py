from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, Sequence

from transcribe.audio.stitch import ChunkTokens, cut_seams as _cut_seams, stitch
from transcribe.contracts import RecognizedToken


class _AudioWindow(Protocol):
    audio: object
    start_ms: int
    end_ms: int


@dataclass
class AudioWindow:
    """A decode window: this window's own audio slice plus its global span."""

    audio: object
    start_ms: int
    end_ms: int


def decode_windows(windows: Sequence[_AudioWindow],
                    decode_fn: Callable[[object], list[RecognizedToken]],
                    seam_window_ms: int, cut_seams: bool = False) -> list[RecognizedToken]:
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

    `cut_seams=True` first gives each window one side of every seam (see
    `stitch.cut_seams`). Use it for deliberately overlapping sub-windows of one
    continuous span (several seconds of overlap), where two decodes of the same
    speech split words differently and token-level dedup interleaves them.
    """
    chunks: list[ChunkTokens] = []
    for w in windows:
        local_tokens = decode_fn(w.audio)
        for t in local_tokens:
            t.start_ms += w.start_ms
            t.end_ms += w.start_ms
        chunks.append(ChunkTokens(local_tokens, w.start_ms, w.end_ms))
    if cut_seams:
        chunks = _cut_seams(chunks)
    return stitch(chunks, seam_window_ms=seam_window_ms)
