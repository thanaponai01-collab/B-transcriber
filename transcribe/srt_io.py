"""SRT/VTT-style subtitle parsing — the one shared place this repo reads a
human-authored cue file back into token dicts.

Used by both tools/make_gold.py (hand-corrected SRT -> gold-set draft) and
transcribe/flywheel/align_srt.py (hand-corrected SRT -> flywheel corrections).
"""

from __future__ import annotations

import re

from transcribe.contracts import detect_script

_SRT_TIME_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)


def _srt_ts_to_ms(h: str, m: str, s: str, ms: str) -> int:
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms)


def parse_srt(text: str) -> list[dict]:
    """Parse SRT (or VTT-style comma/dot timestamps) into gold tokens.

    Each cue becomes one phrase-cue token (5.4 granularity) with an
    auto-detected script tag — matches what harness/make_gold consume."""
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
        if not cue_text:
            continue
        tokens.append({
            "text": cue_text,
            "script": detect_script(cue_text),
            "start_ms": start_ms,
            "end_ms": end_ms,
        })
    return tokens
