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

import random
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
#   v3: cue-structure signals added (HANDOFF_CEILING_BREAK §3.1) — tokens are
#       phrase cues (5.4), so each token's start_ms IS a cue boundary. Adds
#       cue_boundary_error_rate (1 − micro-F1 of ref vs hyp cue-start
#       timestamps, matched the same way as switch points) as a gated signal,
#       plus a hard structural invariant (overlapping_cues, asserted 0 — not a
#       rate) and descriptive-only stats (cue_count_delta, shortest_cue_ms,
#       nonzero_gap_count) for trend-watching. Existing cer_thai/wer_latin/BER
#       definitions are unchanged; only the version bumps, so a fresh baseline
#       starts under the standard metrics_version partitioning.
METRICS_VERSION = 3


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
    # ── cue-structure signals (v3) ──────────────────────────────────────────
    cue_boundary_error_rate: float = 0.0  # 1 − micro-F1 of ref vs hyp cue-start timestamps
    ref_cues: int = 0           # reference cue-start count (aggregation weight)
    hyp_cues: int = 0           # hypothesis cue-start count (micro-F1 numerator base)
    matched_cues: int = 0       # ref↔hyp cue starts matched within tolerance
    overlapping_cues: int = 0   # hard invariant on the hyp alone: must be 0, not a rate
    cue_count_delta: int = 0    # hyp cue count − ref cue count (descriptive only)
    shortest_cue_ms: float | None = None  # shortest hyp cue duration (descriptive only)
    nonzero_gap_count: int = 0  # positive-gap count between consecutive hyp cues (descriptive only)

    @classmethod
    def aggregate(cls, clips: "list[EvalMetrics]") -> "EvalMetrics":
        """Corpus-level metrics from per-clip metrics.

        How a metric aggregates is a property of that metric, so the rule lives
        next to the definition rather than as hand-rolled accumulators in the
        harness. Four different rules apply here and the differences are not
        incidental:

        * `cer_thai` / `wer_latin` / `wer` — reference-weighted means. Each is a
          rate over a stream (Thai characters, Latin words, tokens), so a long
          clip must count for more than a short one.
        * `boundary_error_rate` / `cue_boundary_error_rate` — micro-F1 over the
          summed matched/ref/hyp counts, one F1 at the end. **Not** a weighted
          mean: a ref-weighted mean zeroes out clips with no reference switches,
          so switches hallucinated on a monolingual clip would never be
          penalized (metrics v2).
        * `shortest_cue_ms` — a global minimum, skipping None, so a single
          flash-frame cue anywhere in the corpus is still caught.
        * count fields — plain sums, since they are the weights themselves.

        An empty clip list aggregates to all-zeros rather than raising; the
        empty-gold-set refusal is the harness's job and happens before this.
        """
        def _sum(field: str) -> int:
            return sum(getattr(m, field) for m in clips)

        def _weighted(rate: str, weight: str) -> float:
            total = _sum(weight)
            return sum(getattr(m, rate) * getattr(m, weight) for m in clips) / total if total else 0.0

        shortest = [m.shortest_cue_ms for m in clips if m.shortest_cue_ms is not None]

        return cls(
            cer_thai=_weighted("cer_thai", "thai_chars"),
            wer_latin=_weighted("wer_latin", "latin_words"),
            boundary_error_rate=boundary_f1_error(
                _sum("matched_switches"), _sum("ref_switches"), _sum("hyp_switches")),
            wer=_weighted("wer", "total_words"),
            thai_chars=_sum("thai_chars"),
            latin_words=_sum("latin_words"),
            total_words=_sum("total_words"),
            ref_switches=_sum("ref_switches"),
            hyp_switches=_sum("hyp_switches"),
            matched_switches=_sum("matched_switches"),
            cue_boundary_error_rate=boundary_f1_error(
                _sum("matched_cues"), _sum("ref_cues"), _sum("hyp_cues")),
            ref_cues=_sum("ref_cues"),
            hyp_cues=_sum("hyp_cues"),
            matched_cues=_sum("matched_cues"),
            overlapping_cues=_sum("overlapping_cues"),
            cue_count_delta=_sum("cue_count_delta"),
            shortest_cue_ms=min(shortest) if shortest else None,
            nonzero_gap_count=_sum("nonzero_gap_count"),
        )


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


def _match_points(ref_pts: list[float], hyp_pts: list[float], tol_ms: float) -> int:
    """Count of reference timestamps matched to distinct hypothesis timestamps
    within ±tol_ms. Greedy nearest-match, each hyp point used once. Generic
    over any timestamp stream — used for both switch points and cue starts
    (v3), which share the same "did it land at the right time" question."""
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
    matched = _match_points(ref_pts, hyp_pts, tol_ms)
    return boundary_f1_error(matched, len(ref_pts), len(hyp_pts)), matched


# ── cue structure (v3) ──────────────────────────────────────────────────────────
#
# Tokens ARE phrase cues (5.4 granularity), so a token's start_ms is a cue
# boundary — no new gold-schema field is needed, the existing hand-recut SRTs
# already carry it via transcribe.subtitles.read_subtitles. These functions
# read start_ms/end_ms directly off the token dicts; tokens missing timestamps
# (unit fixtures) are simply skipped rather than raising, so callers that
# don't care about cue timing (e.g. plain WER tests) are unaffected.

def _cue_starts(tokens: list[dict]) -> list[float]:
    """Cue-start timestamps (ms), in order, for tokens that carry one."""
    return [float(t["start_ms"]) for t in tokens if t.get("start_ms") is not None]


def _cue_overlap_count(tokens: list[dict]) -> int:
    """Count of hyp cues whose start is before the previous cue's end — a
    shipped bug (TODO_LEDGER 2026-07-30: cues 20/21 shipped as
    `42,740 --> 42,660`), not a rate to be tolerated. Assumes tokens are given
    in time order, which is true of every pipeline/gold source in this repo."""
    count = 0
    prev_end: float | None = None
    for t in tokens:
        start, end = t.get("start_ms"), t.get("end_ms")
        if start is not None and prev_end is not None and float(start) < prev_end:
            count += 1
        if end is not None:
            prev_end = float(end)
    return count


def _cue_gap_stats(tokens: list[dict]) -> tuple[float | None, int]:
    """(shortest cue duration ms, count of positive gaps between consecutive
    cues). A positive gap is dead air the conform pass should have closed
    (`cue_max_close_gap_ms`) — distinct from an overlap (_cue_overlap_count),
    which is a negative gap and a correctness bug rather than a style debt."""
    durations: list[float] = []
    nonzero_gaps = 0
    prev_end: float | None = None
    for t in tokens:
        start, end = t.get("start_ms"), t.get("end_ms")
        if start is not None and end is not None:
            durations.append(float(end) - float(start))
        if start is not None and prev_end is not None and float(start) > prev_end:
            nonzero_gaps += 1
        if end is not None:
            prev_end = float(end)
    shortest = min(durations) if durations else None
    return shortest, nonzero_gaps


# ── bootstrap confidence intervals (HANDOFF_ONE_ENGINE §3.1) ──────────────────
#
# Every regression verdict to date compared two single point estimates, with
# no way to tell a real 1% move from run-to-run resampling noise on an 8-clip
# corpus (several standing rejections were decided by margins smaller than
# this). Resampling clips with replacement and recomputing the corpus
# aggregate on each draw gives each gated metric a real sampling distribution,
# using the same aggregation rule the harness already uses for it (ratio-of-
# sums for cer_thai/wer_latin, micro-F1 for the two boundary signals) — a CI
# band computed any other way wouldn't mean what the point estimate means.
# Descriptive only: doesn't change any metric's *definition*, so this does
# not bump METRICS_VERSION.

CI_METRICS = ("cer_thai", "wer_latin", "boundary_error_rate", "cue_boundary_error_rate")


def _resample_aggregate(sample: list["EvalMetrics"], metric: str) -> float:
    """Recompute one corpus-aggregate metric over a (possibly resampled) list
    of per-clip EvalMetrics, mirroring harness.run_harness's aggregation rule."""
    if metric == "cer_thai":
        den = sum(m.thai_chars for m in sample)
        return sum(m.cer_thai * m.thai_chars for m in sample) / den if den else 0.0
    if metric == "wer_latin":
        den = sum(m.latin_words for m in sample)
        return sum(m.wer_latin * m.latin_words for m in sample) / den if den else 0.0
    if metric == "boundary_error_rate":
        return boundary_f1_error(
            sum(m.matched_switches for m in sample),
            sum(m.ref_switches for m in sample),
            sum(m.hyp_switches for m in sample),
        )
    if metric == "cue_boundary_error_rate":
        return boundary_f1_error(
            sum(m.matched_cues for m in sample),
            sum(m.ref_cues for m in sample),
            sum(m.hyp_cues for m in sample),
        )
    raise ValueError(f"no CI aggregation rule for metric {metric!r}")


def bootstrap_ci(
    clip_metrics: list["EvalMetrics"],
    metric: str,
    n_draws: int = 1000,
    ci: float = 0.95,
    seed: int | None = 0,
) -> tuple[float, float]:
    """Percentile bootstrap CI for a corpus-level aggregate metric.

    Resamples clips (not characters/words within a clip — the unit a new gold
    clip actually adds) with replacement `n_draws` times and recomputes the
    aggregate each draw. `seed` defaults to a fixed value so re-running the
    harness against an unchanged hypothesis reproduces the same band (Phase A's
    acceptance check: "a re-run of the baseline reproduces within CI"); pass
    `seed=None` for a fresh draw each call.
    """
    n = len(clip_metrics)
    if n == 0:
        return (0.0, 0.0)
    rng = random.Random(seed)
    draws = sorted(
        _resample_aggregate([clip_metrics[rng.randrange(n)] for _ in range(n)], metric)
        for _ in range(n_draws)
    )
    lo = draws[int((1 - ci) / 2 * n_draws)]
    hi = draws[min(n_draws - 1, int((1 + ci) / 2 * n_draws))]
    return lo, hi


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

    # Cue structure (v3): boundary F1 between ref/hyp cue-start timestamps,
    # plus hard/descriptive invariants derived from the hyp cues alone.
    ref_cue_pts = _cue_starts(ref_tokens)
    hyp_cue_pts = _cue_starts(hyp_tokens)
    cue_matched = _match_points(ref_cue_pts, hyp_cue_pts, boundary_tol_ms)
    cue_ber = boundary_f1_error(cue_matched, len(ref_cue_pts), len(hyp_cue_pts))
    overlapping_cues = _cue_overlap_count(hyp_tokens)
    shortest_cue_ms, nonzero_gap_count = _cue_gap_stats(hyp_tokens)

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
        cue_boundary_error_rate=cue_ber,
        ref_cues=len(ref_cue_pts),
        hyp_cues=len(hyp_cue_pts),
        matched_cues=cue_matched,
        overlapping_cues=overlapping_cues,
        cue_count_delta=len(hyp_tokens) - len(ref_tokens),
        shortest_cue_ms=shortest_cue_ms,
        nonzero_gap_count=nonzero_gap_count,
    )
