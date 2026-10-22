"""Subtitle read/write — the one place this repo turns token dicts into an
SRT/VTT cue file and reads a human-authored cue file back into token dicts.

This is the flywheel's round trip: the pipeline writes a cue file, the user
recuts it in an NLE (e.g. Premiere), and transcribe.flywheel.align_srt reads
it back as corrections. tools/make_gold.py and tools/make_finetune_set.py
read hand-corrected cue files into gold-set/fine-tune data through the same
reader.

fps stays an explicit, optional per-call argument on the writer — it is
never resolved from the source media's own probed timebase. The media this
pipeline ingests is frequently audio extracted from footage (no video
stream to probe), so the footage's real frame rate is not recoverable from
the file the pipeline actually sees, and nothing downstream reads
media.fps_num/fps_den back today. See issue #7.
"""

from __future__ import annotations

import re
from fractions import Fraction
from typing import Literal

from transcribe.contracts import detect_script
from transcribe.timebase import Timebase, ms_to_frame

Format = Literal["srt", "vtt"]

_SRT_TIME_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)


def _check_format(fmt: str) -> None:
    if fmt not in ("srt", "vtt"):
        raise ValueError(f"unknown subtitle format {fmt!r} — must be 'srt' or 'vtt'")


def _srt_ts_to_ms(h: str, m: str, s: str, ms: str) -> int:
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms)


def _frame_start_ms(frame: int, tb: Timebase) -> int:
    """The whole millisecond at or just before ``frame`` starts (floor, exact math).

    Premiere snaps an SRT time to a frame of the sequence. A stamp up to 1 ms
    before the frame's exact start names that frame whether Premiere rounds to
    the nearest frame or up; writing the *nearest* millisecond instead could land
    just after the start and be pushed to the next frame by rounding up. It
    fails only if Premiere rounds down, which the live round trip
    (tools/srt_roundtrip.py) checks.
    """
    return frame * tb.fps_den * 1000 // tb.fps_num


def frame_cues(cues: list[dict], tb: Timebase) -> list[dict]:
    """Snap time-ordered cues to whole frames of the target sequence.

    Premiere does this rounding itself on import, cue by cue, and drops a cue
    that rounds to zero frames (PREMIERE_FACTS "Sub-frame SRT cue"). Doing it
    here instead makes the file say exactly what the timeline will show:

    * every boundary is the nearest frame, written as ``_frame_start_ms``
    * every cue lasts at least one frame
    * no cue starts before the previous one ends, even when both snap to one frame
    * a gap shorter than one frame is rounding noise and closes on the frame;
      a gapless input stays gapless
    """
    frame_ms = Fraction(tb.fps_den * 1000, tb.fps_num)
    out: list[dict] = []
    prev_end_ms, prev_end = None, 0
    for cue in cues:
        start = ms_to_frame(cue["start_ms"], tb)
        if prev_end_ms is not None and cue["start_ms"] - prev_end_ms < frame_ms:
            start = prev_end
        start = max(start, prev_end)
        end = max(ms_to_frame(cue["end_ms"], tb), start + 1)
        out.append({**cue, "start_ms": _frame_start_ms(start, tb), "end_ms": _frame_start_ms(end, tb)})
        prev_end_ms, prev_end = cue["end_ms"], end
    return out


def _ms_to_srt(ms: int) -> str:
    h = ms // 3_600_000
    m = (ms % 3_600_000) // 60_000
    s = (ms % 60_000) // 1000
    ms_rem = ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms_rem:03d}"


def _ms_to_vtt(ms: int) -> str:
    h = ms // 3_600_000
    m = (ms % 3_600_000) // 60_000
    s = (ms % 60_000) // 1000
    ms_rem = ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d}.{ms_rem:03d}"


def write_subtitles(tokens: list[dict], fmt: Format, fps: float | None = None) -> str:
    """Format a token list (dicts with text/start_ms/end_ms) as SRT or VTT text.

    fps: if given, snaps cues to the target sequence's frames (``frame_cues``)
    before formatting. Varies per clip/target sequence, so it is passed per
    call (module docstring, issue #7); every Premiere-facing export passes it.

    Returns the formatted text; writing it to disk is the caller's job.
    """
    _check_format(fmt)
    # A blank cue is invalid output, and a blank line inside a cue's text would
    # end the cue early and corrupt the file, so both are dropped/collapsed here.
    # Blanks go before frame snapping so they never push a real cue.
    cues = [t for t in tokens if t["text"].strip()]
    if fps:
        cues = frame_cues(cues, Timebase.from_decimal_fps(fps))

    ms_to_ts = _ms_to_srt if fmt == "srt" else _ms_to_vtt

    lines: list[str] = []
    if fmt == "vtt":
        lines += ["WEBVTT", ""]
    for i, tok in enumerate(cues, 1):
        if fmt == "srt":
            lines.append(str(i))
        lines.append(f"{ms_to_ts(tok['start_ms'])} --> {ms_to_ts(tok['end_ms'])}")
        lines.append(re.sub(r"\n\s*\n+", "\n", tok["text"]))
        lines.append("")

    return "\n".join(lines)


def read_subtitles(text: str, fmt: Format = "srt", *, preserve_line_breaks: bool = False) -> list[dict]:
    """Parse SRT or WebVTT text into gold/correction tokens.

    Each cue becomes one phrase-cue token (5.4 granularity) with an
    auto-detected script tag — matches what harness/make_gold/flywheel
    consume. The comma-or-dot timestamp regex already accepts both SRT and
    VTT timestamp punctuation and the "first line containing a timestamp
    starts the cue" scan already skips any cue-number or WEBVTT header line
    ahead of it, so both formats share one parse path; fmt is accepted (and
    validated) for symmetry with write_subtitles rather than to branch on.

    preserve_line_breaks retains authored display lines for layout learning.
    The default still joins them for recognition scoring and correction import.
    """
    _check_format(fmt)
    text = text.lstrip("﻿")
    blocks = re.split(r"\r?\n\r?\n+", text.strip())
    tokens: list[dict] = []
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip() != ""]
        if not lines:
            continue
        m = None
        content_lines = lines
        for i, ln in enumerate(lines):
            m = _SRT_TIME_RE.search(ln)
            if m:
                content_lines = lines[i + 1:]
                break
        if not m:
            continue
        start_ms = _srt_ts_to_ms(*m.group(1, 2, 3, 4))
        end_ms = _srt_ts_to_ms(*m.group(5, 6, 7, 8))
        cue_text = ("\n" if preserve_line_breaks else " ").join(content_lines).strip()
        # NLE exports (e.g. Premiere) can carry <font color=...> markup for
        # on-screen styling — strip it so it never lands in a correction or
        # gold-set row as if it were transcript text.
        cue_text = re.sub(r"<[^>]+>", "", cue_text).strip()
        if not cue_text:
            continue
        tokens.append({
            "text": cue_text,
            "script": detect_script(cue_text),
            "start_ms": start_ms,
            "end_ms": end_ms,
        })
    return tokens
