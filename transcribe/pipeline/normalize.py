"""Phase 6 — Normalization: script-boundary spacing, exception lexicon, Thai cleanup."""

from __future__ import annotations

import re
from pathlib import Path

_THAI_RE = re.compile(r"[฀-๿]")

# Script-boundary spacing patterns (lookbehind/lookahead safe in Python re)
_THAI_TO_LATIN = re.compile(r"(?<=[฀-๿])(?=[a-zA-Z0-9])")
_LATIN_TO_THAI = re.compile(r"(?<=[a-zA-Z0-9])(?=[฀-๿])")


def _load_exception_lexicon(config: dict) -> list[str]:
    """Load exception terms from config (no-split list)."""
    return list(config.get("normalization", {}).get("exception_lexicon", []))


def _protect_exceptions(text: str, exceptions: list[str]) -> tuple[str, dict[str, str]]:
    """Replace exception terms with placeholders before spacing."""
    placeholders: dict[str, str] = {}
    for term in sorted(exceptions, key=len, reverse=True):  # longest first
        if term in text:
            key = f"\x00EX{len(placeholders)}\x00"
            placeholders[key] = term
            text = text.replace(term, key)
    return text, placeholders


def _restore_exceptions(text: str, placeholders: dict[str, str]) -> str:
    for key, term in placeholders.items():
        text = text.replace(key, term)
    return text


def _add_boundary_spaces(text: str) -> str:
    text = _THAI_TO_LATIN.sub(" ", text)
    text = _LATIN_TO_THAI.sub(" ", text)
    return text


def _thai_cleanup(text: str) -> str:
    """Apply PyThaiNLP normalization for Thai text."""
    try:
        from pythainlp.util import normalize as thai_normalize
        return thai_normalize(text)
    except ImportError:
        return text


def normalize(text: str, config: dict | None = None) -> str:
    """
    Normalize a transcript string:
    1. Protect exception lexicon items.
    2. Add spaces at Thai↔Latin boundaries.
    3. PyThaiNLP Thai cleanup (tone marks, sara order, ๆ, numerals).
    4. Restore exceptions.
    5. Collapse multiple spaces.
    """
    config = config or {}
    exceptions = _load_exception_lexicon(config)

    text, placeholders = _protect_exceptions(text, exceptions)
    text = _add_boundary_spaces(text)
    text = _thai_cleanup(text)
    text = _restore_exceptions(text, placeholders)
    text = re.sub(r" {2,}", " ", text).strip()
    return text


def normalize_tokens(tokens: list[dict], config: dict | None = None) -> list[dict]:
    """Normalize the text field of each token dict in-place (returns new list)."""
    return [{**t, "text": normalize(t["text"], config)} for t in tokens]
