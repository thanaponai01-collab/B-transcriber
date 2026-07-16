"""Accuracy metrics for Thai-primary code-switch ASR.

Three signals, each measured on the unit that is actually well-defined:

* **CER over Thai spans** — Thai has no word boundaries, so word-level WER on Thai
  is ill-posed (newmm and attacut disagree on the same sentence, making your gold
  segmentation a moving target). We compare the *character* stream of all Thai-script
  content instead — tokenization-free.
* **WER over Latin spans** — English/Latin words have real boundaries; word edit
  distance is the right unit. Comparison is case-insensitive (casing is an output
  policy, not an accuracy signal — see STYLE_GUIDE.md).
* **Temporal switch-point error** — did the engine detect each Thai↔Latin language
  transition at roughly the right *time*? Matched against reference switch timestamps
  within a tolerance window, scored as 1 − F1. A positional metric would reward an
  engine that emits the right words in the wrong place; this does not.

`wer` (overall word-level) is retained as a coarse, tokenization-sensitive signal —
useful for sanity, never the primary gate.

When `config` is passed, the SAME normalization is applied to reference and hypothesis
before scoring, so the metric never compares against an un-normalized (moving) target.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_THAI_CHAR = re.compile(r"[฀-๿]")
_LATIN_RUN = re.compile(r"[a-z0-9]+")  # applied to lowercased text

# Version of the metric definitions. Bump whenever a change makes new scores
# incomparable to old ones — the regression gate then partitions baselines by
# this value (store.get_last_passing_eval), so the first run under a new
# version establishes a fresh baseline instead of tripping the gate against
# numbers computed by a different rule.
#   v1: switch points from token-level `script` only (a `mixed` phrase cue
#       could never yield a switch → BER was structurally 0 at cue
#       granularity); corpus BER = per-sample 1−F1 weighted by ref switches
#       (false-positive switches on zero-switch samples were unpenalized).
#   v2: switch points derived character-by-character inside every token, with
#       the timestamp linearly interpolated across the token's span; corpus
#       BER = 1 − micro-F1 over summed matched/ref/hyp switch counts.
METRICS_VERSION = 2


@dataclass
class EvalMetrics:
    cer_thai: float             # character error rate over Thai-script content
    wer_latin: float            # word error rate over Latin-script content
    boundary_error_rate: float  # temporal switch-point error (1 − F1)
    wer: float                  # overall word-level WER (coarse, tokenizer-sensitive)
    thai_chars: int             # reference Thai-character count (aggregation weight)
    latin_words: int            # reference Latin-word count (aggregation weight)
    total_words: int            # reference token count (aggregation weight)
    ref_switches: int           # reference switch-point count (aggregation weight)
    hyp_switches: int = 0       # hypothesis switch-point count (micro-F1 numerator base)
    matched_switches: int = 0   # ref↔hyp switch points matched within tolerance


# ── regression gate ───────────────────────────────────────────────────────────

def regressed(now: float, base: float, tol_frac: float = 1.02, abs_floor: float = 0.005) -> bool:
    """True if `now` is worse than `base` by more than the allowed band.

    Relative tolerance alone collapses to zero when base≈0 (0 * 1.02 == 0), so a
    perfect or tiny baseline would trip the gate on any nonzero score. Floor the
    band with an absolute slack (#6).
    """
    return now > max(base * tol_frac, base + abs_floor)


# ── edit distance ─────────────────────────────────────────────────────────────

def _edit_distance(ref: list | str, hyp: list | str) -> int:
    """Levenshtein distance over any two indexable sequences (chars or words).

    Uses rapidfuzz (C, ~100× faster) when present — the harness reruns on every
    bias update and a 15-min Thai gold set is ~10^8 pure-Python ops per signal.
    Falls back to the pure-Python DP if rapidfuzz is absent.
    """
    try:
        from rapidfuzz.distance import Levenshtein
        return Levenshtein.distance(ref, hyp)
    except ImportError:
        return _edit_distance_py(ref, hyp)


def _edit_distance_py(ref: list | str, hyp: list | str) -> int:
    n, m = len(ref), len(hyp)
    dp = list(range(m + 1))
    for i in range(1, n + 1):
        prev = dp[:]
        dp[0] = i
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                dp[j] = prev[j - 1]
            else:
                dp[j] = 1 + min(prev[j], dp[j - 1], prev[j - 1])
    return dp[m]


def _error_rate(ref: list | str, hyp: list | str) -> float:
    if not ref:
        return 0.0 if not hyp else 1.0
    return _edit_distance(ref, hyp) / len(ref)


# kept as a public name for callers/tests that want plain word edit distance
def word_error_rate(reference: list[str], hypothesis: list[str]) -> float:
    return _error_rate(reference, hypothesis)


# ── stream extraction (tokenization-free) ──────────────────────────────────────

def _thai_char_stream(tokens: list[dict]) -> str:
    """All Thai-script characters across tokens, in order, with no spaces.

    Independent of how the human or engine split Thai into 'words'."""
    return "".join(c for t in tokens for c in t["text"] if _THAI_CHAR.match(c))


def _latin_word_stream(tokens: list[dict]) -> list[str]:
    """Lowercased maximal Latin/digit runs across tokens, in order."""
    words: list[str] = []
    for t in tokens:
        words.extend(_LATIN_RUN.findall(t["text"].lower()))
    return words


# ── temporal switch points ─────────────────────────────────────────────────────

def _is_switch(prev: str, curr: str) -> bool:
    return (prev == "thai" and curr == "latin") or (prev == "latin" and curr == "thai")


def _char_script(c: str) -> str | None:
    """'thai' | 'latin' | None (neutral: digits, punctuation, space).

    Mirrors contracts.detect_script at character level: only Thai-block chars
    and ASCII letters carry a script; digits stay neutral so "ก 2 ก" is not a
    switch (STYLE_GUIDE §4: the test is how the word was *pronounced*)."""
    if _THAI_CHAR.match(c):
        return "thai"
    if c.isascii() and c.isalpha():
        return "latin"
    return None


def _switch_points(tokens: list[dict]) -> list[float]:
    """Timestamps (ms) of Thai↔Latin transitions, derived character-by-character.

    Tokens are phrase cues, so a real code-switch usually happens INSIDE a
    `mixed` cue — deriving switches from the token-level script field alone
    (metrics v1) made those invisible and pinned BER at a structural 0.0.
    Instead, walk every character of every token: a Thai↔Latin transition in
    the character stream is a switch, and its timestamp is linearly
    interpolated across the token's [start_ms, end_ms] span by character
    offset (uniform char rate — an approximation, but the same one on both
    sides of the comparison; widen boundary_tol_ms if it proves too tight).

    When a token has no start_ms (unit fixtures), falls back to token index +
    intra-token char fraction so identical sequences still align under
    tolerance."""
    points: list[float] = []
    prev: str | None = None
    for i, t in enumerate(tokens):
        text = t["text"]
        start = t.get("start_ms")
        end = t.get("end_ms")
        n = max(1, len(text))
        for k, c in enumerate(text):
            script = _char_script(c)
            if script is None:
                continue
            if prev is not None and _is_switch(prev, script):
                if start is None:
                    points.append(float(i) + k / n)
                else:
                    span = float(end) - float(start) if end is not None else 0.0
                    points.append(float(start) + span * (k / n))
            prev = script
    return points


def _match_switch_points(ref_pts: list[float], hyp_pts: list[float], tol_ms: float) -> int:
    """Count of reference switch points matched to distinct hypothesis switch
    points within ±tol_ms. Greedy nearest-match, each hyp point used once."""
    used: set[int] = set()
    matched = 0
    for r in ref_pts:
        best_j, best_d = -1, None
        for j, h in enumerate(hyp_pts):
            if j in used:
                continue
            d = abs(h - r)
            if d <= tol_ms and (best_d is None or d < best_d):
                best_j, best_d = j, d
        if best_j >= 0:
            used.add(best_j)
            matched += 1
    return matched


def boundary_f1_error(matched: int, ref_count: int, hyp_count: int) -> float:
    """1 − F1 from switch-point counts. Also the corpus-level aggregation rule:
    sum matched/ref/hyp over all samples and call this once (micro-F1), so
    hallucinated switches on zero-switch samples are penalized instead of
    vanishing under a ref-weighted mean (metrics v2)."""
    if not ref_count and not hyp_count:
        return 0.0
    precision = matched / hyp_count if hyp_count else 0.0
    recall = matched / ref_count if ref_count else 0.0
    if precision + recall == 0.0:
        return 1.0
    f1 = 2 * precision * recall / (precision + recall)
    return 1.0 - f1


def _temporal_boundary_error(
    ref_pts: list[float], hyp_pts: list[float], tol_ms: float
) -> tuple[float, int]:
    """(1 − F1, matched count) of ref switch points vs hyp switch points."""
    matched = _match_switch_points(ref_pts, hyp_pts, tol_ms)
    return boundary_f1_error(matched, len(ref_pts), len(hyp_pts)), matched


# ── normalization (identical treatment of ref and hyp) ─────────────────────────

def _normalize_tokens(tokens: list[dict], config: dict) -> list[dict]:
    from transcribe.pipeline.normalize import normalize  # lazy: avoid hard dep
    out = []
    for t in tokens:
        nt = dict(t)
        nt["text"] = normalize(t["text"], config)
        out.append(nt)
    return out


# ── public entry point ──────────────────────────────────────────────────────────

def compute_metrics(
    ref_tokens: list[dict],          # [{"text", "script", "start_ms"?}, ...]
    hyp_tokens: list[dict],
    config: dict | None = None,      # when given, normalize BOTH sides identically
    boundary_tol_ms: float = 300.0,
) -> EvalMetrics:
    if config is not None:
        ref_tokens = _normalize_tokens(ref_tokens, config)
        hyp_tokens = _normalize_tokens(hyp_tokens, config)

    # Thai: character error rate (tokenization-free)
    ref_thai = _thai_char_stream(ref_tokens)
    hyp_thai = _thai_char_stream(hyp_tokens)
    cer_thai = _error_rate(ref_thai, hyp_thai)

    # Latin: word error rate, case-insensitive
    ref_latin = _latin_word_stream(ref_tokens)
    hyp_latin = _latin_word_stream(hyp_tokens)
    wer_latin = _error_rate(ref_latin, hyp_latin)

    # Temporal switch-point error
    ref_pts = _switch_points(ref_tokens)
    hyp_pts = _switch_points(hyp_tokens)
    ber, matched = _temporal_boundary_error(ref_pts, hyp_pts, boundary_tol_ms)

    # Overall word-level WER (coarse)
    ref_words = [t["text"] for t in ref_tokens]
    hyp_words = [t["text"] for t in hyp_tokens]
    overall_wer = _error_rate(ref_words, hyp_words)

    return EvalMetrics(
        cer_thai=cer_thai,
        wer_latin=wer_latin,
        boundary_error_rate=ber,
        wer=overall_wer,
        thai_chars=len(ref_thai),
        latin_words=len(ref_latin),
        total_words=len(ref_words),
        ref_switches=len(ref_pts),
        hyp_switches=len(hyp_pts),
        matched_switches=matched,
    )
