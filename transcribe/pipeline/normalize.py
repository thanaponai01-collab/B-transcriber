from __future__ import annotations

import re
from dataclasses import replace

from transcribe.contracts import PipelineToken

_THAI_RE = re.compile(r"[฀-๿]")

_THAI_TO_LATIN = re.compile(r"(?<=[฀-๿])(?=[a-zA-Z0-9])")
_LATIN_TO_THAI = re.compile(r"(?<=[a-zA-Z0-9])(?=[฀-๿])")

_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")

_MAI_YAMOK = re.compile(r"(?:\s*ๆ)+")


def _load_exception_lexicon(config: dict) -> list[str]:
    return list(config.get("normalization", {}).get("exception_lexicon", []))


def _protect_exceptions(text: str, exceptions: list[str]) -> tuple[str, dict[str, str]]:
    placeholders: dict[str, str] = {}
    for term in sorted(exceptions, key=len, reverse=True):
        if term in text:
            key = f"\x00EX{len(placeholders)}\x00"
            placeholders[key] = term
            text = text.replace(term, key)
    return text, placeholders


def _restore_exceptions(text: str, placeholders: dict[str, str]) -> str:
    for key, term in placeholders.items():
        text = text.replace(key, term)
    return text


def _normalize_thai_digits(text: str, enabled: bool) -> str:
    return text.translate(_THAI_DIGITS) if enabled else text


def _canonical_mai_yamok(text: str, enabled: bool) -> str:
    return _MAI_YAMOK.sub("ๆ", text) if enabled else text


def _add_boundary_spaces(text: str) -> str:
    text = _THAI_TO_LATIN.sub(" ", text)
    text = _LATIN_TO_THAI.sub(" ", text)
    return text


def _thai_cleanup(text: str) -> str:
    try:
        from pythainlp.util import normalize as thai_normalize
        return thai_normalize(text)
    except ImportError:
        return text


def normalize(text: str, config: dict | None = None) -> str:
    """Normalize a transcript string per STYLE_GUIDE.md."""
    config = config or {}
    norm_cfg = config.get("normalization", {})
    exceptions = _load_exception_lexicon(config)

    text = _normalize_thai_digits(text, norm_cfg.get("thai_digits", True))
    text = _canonical_mai_yamok(text, norm_cfg.get("mai_yamok_attach", True))
    text = _add_boundary_spaces(text)
    text, placeholders = _protect_exceptions(text, exceptions)
    text = _thai_cleanup(text)
    text = _restore_exceptions(text, placeholders)
    text = re.sub(r" {2,}", " ", text).strip()
    return text


def normalize_tokens(tokens: list[PipelineToken], config: dict | None = None) -> list[PipelineToken]:
    return [replace(t, text=normalize(t.text, config)) for t in tokens]


def _silence_overlap_ms(tok: PipelineToken, silences: list[tuple[int, int]]) -> int:
    """Total milliseconds of a token's span that fall inside any silence span."""
    total = 0
    for s_start, s_end in silences:
        total += max(0, min(tok.end_ms, s_end) - max(tok.start_ms, s_start))
    return total


def drop_tokens_over_silence(
    tokens: list[PipelineToken],
    silence_spans: list[tuple[int, int]],
    overlap: float = 0.8,
    max_confidence: float | None = None,
) -> list[PipelineToken]:
    """Drop tokens that sit mostly inside VAD silence.

    A token whose span overlaps silence by >= ``overlap`` of its own duration is
    a hallucination *candidate*.
    A token straddling a boundary (e.g. 50% overlap) is kept.

    When ``max_confidence`` is set, a silence-overlapping token is only
    dropped if its confidence is also <= that threshold (or unknown). Re-indexes
    survivors so idx stays contiguous.
    """
    if not silence_spans or not tokens:
        return tokens
    kept: list[PipelineToken] = []
    for tok in tokens:
        duration = max(1, tok.end_ms - tok.start_ms)
        over_silence = _silence_overlap_ms(tok, silence_spans) / duration >= overlap
        if not over_silence:
            kept.append(tok)
            continue
        if (max_confidence is not None and tok.confidence is not None
                and tok.confidence > max_confidence):
            kept.append(tok)
            continue
    for new_idx, tok in enumerate(kept):
        tok.idx = new_idx
    return kept
