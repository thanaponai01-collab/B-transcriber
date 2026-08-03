"""cutdeck/words.py — Phase 1: the word timeline (HANDOFF_CUTDECK_WORDLEVEL.md Phase 1).

Word-level cutting (fillers, stutters, mid-speech blades — Phase 2) needs real
word spans, but faster-whisper's raw per-word output for spaceless Thai is
sub-word fragments (see HANDOFF_CUTDECK_WORDLEVEL.md F2 — e.g. `{'text':
'เท', 1520-2120}`, `{'text': 'ส', 2120-2420}`). A per-character timeline
reconstructs the full text, then ``pythainlp.word_tokenize`` finds real word
boundaries, and each resulting token is mapped back to a time span via the
timeline.

This is the one implementation of that reconstruction. ``transcribe.engines.
faster_whisper._group_words_into_cues`` calls :func:`timed_tokens` for its own
steps 1-3 rather than duplicating this logic (see HANDOFF F1/F2 — two
implementations of Thai word-timeline reconstruction is exactly the kind of
drift that produced the dead filler rule).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# (text, start_ms, end_ms, confidence) — a raw word-piece fragment.
Piece = tuple[str, int, int, Optional[float]]
# (text, start_ms, end_ms, confidence, char_pos) — a token mapped back onto
# the char timeline. char_pos is the token's offset into the reconstructed
# full_text, for callers that need to align against offsets computed on that
# same text (e.g. faster_whisper's sentence-boundary cue breaks).
TimedToken = tuple[str, int, int, Optional[float], int]


@dataclass(frozen=True)
class Word:
    text: str
    start_ms: int
    end_ms: int
    confidence: Optional[float]


def timed_tokens(pieces: list[Piece]) -> tuple[str, list[TimedToken]]:
    """Rebuild a per-character timeline from word-piece fragments and segment
    it into real words via pythainlp.

    Returns ``(full_text, timed)``. Pure post-processing on ``(text, start,
    end, confidence)`` tuples — no model-specific logic, so it stays behind
    the engine contract and works for any engine that populates
    ``EngineResult.raw["words"]``.
    """
    from pythainlp.tokenize import word_tokenize

    # 1. per-character timeline (each char inherits its source piece's span + confidence)
    chartime: list[tuple[int, int]] = []
    charconf: list[Optional[float]] = []
    chars: list[str] = []
    for txt, s, e, conf in pieces:
        for ch in txt:
            chars.append(ch)
            chartime.append((s, e))
            charconf.append(conf)
    if not chars:
        return "", []
    full_text = "".join(chars)

    # 2. real word boundaries (pythainlp keeps Latin runs and spaces intact)
    toks = word_tokenize(full_text, keep_whitespace=True)

    # 3. map each token back to its time span + confidence + char start via the char timeline
    timed: list[TimedToken] = []
    pos = 0
    for t in toks:
        start = chartime[pos][0]
        end = chartime[pos + len(t) - 1][1]
        confs = [c for c in charconf[pos:pos + len(t)] if c is not None]
        conf = sum(confs) / len(confs) if confs else None
        timed.append((t, start, end, conf, pos))
        pos += len(t)
    return full_text, timed


def words_from_pieces(pieces: list[Piece]) -> list[Word]:
    """Word timeline for CutDeck's word-level rules (fillers, repeats, blades).

    Whitespace tokens from ``word_tokenize`` are dropped — CutDeck rules match
    and cut real words, never the space between them. Latin runs and Thai
    runs in the same piece list each come back as their own word(s); the
    dropped whitespace is what kept them from being glued together.
    """
    _, timed = timed_tokens(pieces)
    return [Word(t, s, e, conf) for t, s, e, conf, _pos in timed if t.strip()]


def words_for_job(conn, job_id: int, engine_slot: str = "a") -> list[Word]:
    """Word timeline for a persisted job, from ``engine_result.raw_words_json``.

    Returns ``[]`` when the engine reported no raw words (chunk engines, or
    any engine that never populated ``raw["words"]``) so every caller degrades
    to today's cue-level behaviour instead of crashing — see HANDOFF F2.
    """
    from transcribe.db import store

    result = store.get_engine_result(conn, job_id, engine_slot)
    if result is None or not result.raw_words_json:
        return []
    raw = json.loads(result.raw_words_json)
    pieces: list[Piece] = [
        (w["text"], w["start_ms"], w["end_ms"], w.get("confidence"))
        for w in raw
    ]
    return words_from_pieces(pieces)
