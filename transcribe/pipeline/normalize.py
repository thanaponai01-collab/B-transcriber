"""Phase 6 — Normalization: an explicit, deterministic text policy.

This is the single source of truth for the transcription style decisions in
STYLE_GUIDE.md. It is applied to pipeline hypotheses (run.py) AND, identically,
to the gold set during evaluation (eval/metrics.py) — so the metric never scores
against an un-normalized, moving target.

Every transform here is deterministic and tokenization-free. Decisions that
require segmentation or semantics (loanword script choice, number *verbalization*
สิบ↔10) are gold-authoring policy, not code — see STYLE_GUIDE.md.

Order matters: digits → mai yamok → boundary spacing → Thai cleanup.
"""

from __future__ import annotations

import re
from dataclasses import replace

from transcribe.contracts import PipelineToken

_THAI_RE = re.compile(r"[฀-๿]")

# Script-boundary spacing patterns (lookbehind/lookahead safe in Python re)
_THAI_TO_LATIN = re.compile(r"(?<=[฀-๿])(?=[a-zA-Z0-9])")
_LATIN_TO_THAI = re.compile(r"(?<=[a-zA-Z0-9])(?=[฀-๿])")

# Thai digits ๐-๙ → Arabic 0-9. Deterministic; unlike verbalization (สิบ↔10)
# this never requires context, so we always apply it.
_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")

# Mai yamok (ๆ) = "repeat preceding word". Canonical form attaches it to the
# word with no preceding whitespace; we do NOT expand it, because expansion
# requires word segmentation (ambiguous). Collapse runs and strip leading space.
_MAI_YAMOK = re.compile(r"\s*ๆ+")


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


def _normalize_thai_digits(text: str, enabled: bool) -> str:
    """Map Thai numerals ๐-๙ to Arabic 0-9 (STYLE_GUIDE: numbers as Arabic digits)."""
    return text.translate(_THAI_DIGITS) if enabled else text


def _canonical_mai_yamok(text: str, enabled: bool) -> str:
    """Collapse 'word ๆ' / 'wordๆๆ' to the canonical attached single 'wordๆ'."""
    return _MAI_YAMOK.sub("ๆ", text) if enabled else text


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
    Normalize a transcript string per STYLE_GUIDE.md:
    0. Protect exception lexicon items (brands/mixed-script proper nouns).
    1. Thai numerals → Arabic digits (policy: numbers written as Arabic).
    2. Mai yamok (ๆ) → canonical attached form (no expansion).
    3. Add spaces at Thai↔Latin boundaries.
    4. PyThaiNLP Thai cleanup (tone-mark/sara ordering).
    5. Restore exceptions.
    6. Collapse multiple spaces.

    The same function is applied to hypotheses and to the gold set, so policy
    toggles can never desync the two sides of an evaluation.
    """
    config = config or {}
    norm_cfg = config.get("normalization", {})
    exceptions = _load_exception_lexicon(config)

    text, placeholders = _protect_exceptions(text, exceptions)
    text = _normalize_thai_digits(text, norm_cfg.get("thai_digits", True))
    text = _canonical_mai_yamok(text, norm_cfg.get("mai_yamok_attach", True))
    text = _add_boundary_spaces(text)
    text = _thai_cleanup(text)
    text = _restore_exceptions(text, placeholders)
    text = re.sub(r" {2,}", " ", text).strip()
    return text


def normalize_tokens(tokens: list[PipelineToken], config: dict | None = None) -> list[PipelineToken]:
    return [replace(t, text=normalize(t.text, config)) for t in tokens]
