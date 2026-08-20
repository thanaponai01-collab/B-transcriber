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
from typing import Literal

from transcribe.contracts import detect_script

Format = Literal["srt", "vtt"]

_SRT_TIME_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)


def _check_format(fmt: str) -> None:
    if fmt not in ("srt", "vtt"):
        raise ValueError(f"unknown subtitle format {fmt!r} — must be 'srt' or 'vtt'")


def _srt_ts_to_ms(h: str, m: str, s: str, ms: str) -> int:
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms)


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

    fps: if given, quantizes cue boundaries to the target sequence's frame
    rate before formatting (varies per clip/target sequence, so must be
    passed per call — see the module docstring and issue #7).

    Returns the formatted text; writing it to disk is the caller's job.
    """
    _check_format(fmt)
    if fps:
        tokens = _quantize_tokens(tokens, fps)

    ms_to_ts = _ms_to_srt if fmt == "srt" else _ms_to_vtt

    lines: list[str] = []
    if fmt == "vtt":
        lines += ["WEBVTT", ""]
    for i, tok in enumerate(tokens, 1):
        if fmt == "srt":
            lines.append(str(i))
        lines.append(f"{ms_to_ts(tok['start_ms'])} --> {ms_to_ts(tok['end_ms'])}")
        lines.append(tok["text"])
        lines.append("")

    return "\n".join(lines)


def read_subtitles(text: str, fmt: Format = "srt") -> list[dict]:
    """Parse SRT or WebVTT text into gold/correction tokens.

    Each cue becomes one phrase-cue token (5.4 granularity) with an
    auto-detected script tag — matches what harness/make_gold/flywheel
    consume. The comma-or-dot timestamp regex already accepts both SRT and
    VTT timestamp punctuation and the "first line containing a timestamp
    starts the cue" scan already skips any cue-number or WEBVTT header line
    ahead of it, so both formats share one parse path; fmt is accepted (and
    validated) for symmetry with write_subtitles rather than to branch on.
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
        cue_text = " ".join(content_lines).strip()
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
