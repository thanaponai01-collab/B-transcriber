"""Flywheel Phase 9a — diff raw ASR output vs human corrections → correction pairs."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Optional

# Tokens are now ~7 s phrase cues (faster-whisper). A one-word edit on a cue would
# otherwise promote the whole sentence as a bias "term", devouring the prompt
# budget and biasing toward sentence repetition. When either side is longer than
# this, extract just the minimal changed word/phrase (5.3).
_SPAN_THRESHOLD = 15


@dataclass
class CorrectionPair:
    token_idx: int
    raw_text: str
    corrected_text: str            # full corrected cue — audit + editor display
    source_engine: str
    reason: Optional[str] = None   # GAP-7: optional one-tap tag from the editor
    corrected_span: Optional[str] = None  # 5.3: minimal promotable word/phrase


def _word_spans(text: str) -> list[tuple[str, int, int]]:
    """(word, start, end) over `text`. newmm for Thai, whitespace preserved so
    Latin runs and spaces keep their offsets. Falls back to a crude split if
    pythainlp is unavailable."""
    try:
        from pythainlp.tokenize import word_tokenize
        toks = word_tokenize(text, keep_whitespace=True)
    except Exception:
        toks = text.split(" ")
    spans = []
    pos = 0
    for t in toks:
        spans.append((t, pos, pos + len(t)))
        pos += len(t)
    return spans


def _extract_changed_span(raw: str, corrected: str, threshold: int = _SPAN_THRESHOLD) -> str:
    """Minimal changed region of `corrected` vs `raw`, expanded to word boundaries.

    Returns the full `corrected` when both sides are short (nothing to gain) or if
    no change is found. For "…ChatGBT…" → "…ChatGPT…" this yields "ChatGPT", not
    the whole sentence.

    Diffs at word granularity, not characters: a character-level diff on Thai text
    gets smeared across the whole cue when a short syllable (e.g. "อ" inside a
    removed "อ๋อ") also recurs in unrelated nearby words, since SequenceMatcher
    then treats most of the string as "changed". Word tokens don't have that
    collision.
    """
    if len(raw) <= threshold and len(corrected) <= threshold:
        return corrected
    raw_words = [w for (w, _s, _e) in _word_spans(raw)]
    corr_words = [w for (w, _s, _e) in _word_spans(corrected)]
    sm = difflib.SequenceMatcher(a=raw_words, b=corr_words, autojunk=False)
    lo = hi = None
    for tag, _i1, _i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            lo = j1 if lo is None else min(lo, j1)
            hi = j2 if hi is None else max(hi, j2)
    if lo is None:
        return corrected
    hi = max(hi, lo + 1)
    # Widen outward until the picked range has non-whitespace content — a pure
    # deletion (e.g. dropping a filler word) can leave the diff straddling only
    # a whitespace token, which would otherwise strip to "".
    while True:
        picked = "".join(corr_words[lo:hi]).strip()
        if picked or (lo == 0 and hi >= len(corr_words)):
            return picked or corrected
        if lo > 0:
            lo -= 1
        if hi < len(corr_words):
            hi += 1


def diff_corrections(
    original_tokens: list[dict],   # from DB: {"idx", "text", "source_engine", ...}
    corrected_tokens: list[dict],  # from editor: {"idx", "text", "reason"?, ...}
) -> list[CorrectionPair]:
    """
    Compare original and corrected token lists by idx.
    Returns correction pairs only where text changed.
    """
    orig_by_idx = {t["idx"]: t for t in original_tokens}
    corr_by_idx = {t["idx"]: t for t in corrected_tokens}

    pairs = []
    for idx, corr in corr_by_idx.items():
        orig = orig_by_idx.get(idx)
        if orig is None:
            continue
        if orig["text"] != corr["text"]:
            pairs.append(CorrectionPair(
                token_idx=idx,
                raw_text=orig["text"],
                corrected_text=corr["text"],
                source_engine=orig.get("source_engine", "unknown"),
                reason=corr.get("reason"),
                corrected_span=_extract_changed_span(orig["text"], corr["text"]),
            ))
    return pairs
