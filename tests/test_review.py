"""Tests for review flags, spoken-Thai lexicon, and word tokenization deduplication (issue #75)."""
from unittest.mock import patch
import pytest

from transcribe import review
from transcribe.service import review_flags


def test_colloquial_particles_do_not_trigger_unfamiliar_thai_fragments():
    """1. Colloquial particles from transcribe/thai/atoms.py (เนี้ย, เนี่ย, นึง, มั้ย)
    do not trigger 'unfamiliar Thai fragments'."""
    cue = {
        "text": "อันนี้เนี้ยมันดีเนี่ย อีกอันนึงใช่มั้ย",
        "start_ms": 1000,
        "end_ms": 3000,
        "confidence": 0.95,
    }
    reasons = review.suspicion_reasons(cue)
    unfamiliar = [r for r in reasons if "unfamiliar Thai fragments" in r]
    assert not unfamiliar, f"Expected no unfamiliar fragments, got: {unfamiliar}"


def test_multicue_high_compression_segment_does_not_blanket_flag_nonrepetitive_cues():
    """2. A multi-cue segment whose compression_ratio > 2.4 does not blanket-flag
    non-repetitive sibling cues as 'repetitive text'."""
    cues = [
        {"text": "สวัสดีครับทุกท่าน วันนี้เรามาพบกันอีกครั้ง", "start_ms": 0, "end_ms": 2500, "confidence": 0.95},
        {"text": "ครับ ครับ ครับ ครับ ครับ ครับ ครับ", "start_ms": 2500, "end_ms": 5000, "confidence": 0.95},
        {"text": "ยินดีต้อนรับสู่รายการของเรา", "start_ms": 5000, "end_ms": 7500, "confidence": 0.95},
    ]
    # Single 10s segment with high compression covering all three cues
    segments = [
        {"start_ms": 0, "end_ms": 8000, "avg_logprob": -0.3, "no_speech_prob": 0.05, "compression_ratio": 2.5}
    ]
    flags = review_flags(cues, segments)

    # Cue 0 and Cue 2 are clean non-repetitive speech and must not be flagged for repetitive text
    flagged_reasons_by_cue = {f["cue_index"]: f["reasons"] for f in flags}
    if 0 in flagged_reasons_by_cue:
        assert "repetitive text" not in flagged_reasons_by_cue[0]
    if 2 in flagged_reasons_by_cue:
        assert "repetitive text" not in flagged_reasons_by_cue[2]

    # Cue 1 has repetition and should be flagged
    assert 1 in flagged_reasons_by_cue
    assert "repetitive text" in flagged_reasons_by_cue[1]


def test_suspicion_reasons_uses_provided_words_without_retokenizing():
    """Tokenized words can be passed into suspicion_reasons to avoid re-tokenizing."""
    cue = {"text": "สวัสดีครับ", "start_ms": 0, "end_ms": 1000, "confidence": 0.95}
    provided_words = ["สวัสดี", "ครับ"]

    import pythainlp.tokenize
    with patch.object(pythainlp.tokenize, "word_tokenize", wraps=pythainlp.tokenize.word_tokenize) as spy:
        reasons = review.suspicion_reasons(cue, words=provided_words)
        assert spy.call_count == 0
        assert not any("unfamiliar Thai fragments" in r for r in reasons)
