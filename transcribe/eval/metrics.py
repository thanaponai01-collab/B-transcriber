from __future__ import annotations

import random
import re
from dataclasses import dataclass

_THAI_CHAR = re.compile(r"[฀-๿]")
_LATIN_RUN = re.compile(r"[a-z0-9]+")

METRICS_VERSION = 4

ORPHAN_MAX_MS = 300.0
ORPHAN_ISOLATION_MS = 300.0


@dataclass
class EvalMetrics:
    cer_thai: float
    wer_latin: float
    boundary_error_rate: float
    wer: float
    thai_chars: int
    latin_words: int
    total_words: int
    ref_switches: int
    hyp_switches: int = 0
    matched_switches: int = 0
    cue_boundary_error_rate: float = 0.0
    ref_cues: int = 0
    hyp_cues: int = 0
    matched_cues: int = 0
    overlapping_cues: int = 0
    cue_count_delta: int = 0
    shortest_cue_ms: float | None = None
    nonzero_gap_count: int = 0
    speech_coverage_miss: float = 0.0
    ref_speech_ms: float = 0.0
    missed_speech_ms: float = 0.0
    orphan_cues: int = 0

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
            speech_coverage_miss=_weighted("speech_coverage_miss", "ref_speech_ms"),
            ref_speech_ms=_sum("ref_speech_ms"),
            missed_speech_ms=_sum("missed_speech_ms"),
            orphan_cues=_sum("orphan_cues"),
        )


def regressed(now: float, base: float, tol_frac: float = 1.02, abs_floor: float = 0.005) -> bool:
    return now > max(base * tol_frac, base + abs_floor)


def _edit_distance(ref: list | str, hyp: list | str) -> int:
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


def _thai_char_stream(tokens: list[dict]) -> str:
    return "".join(c for t in tokens for c in t["text"] if _THAI_CHAR.match(c))


def _latin_word_stream(tokens: list[dict]) -> list[str]:
    words: list[str] = []
    for t in tokens:
        words.extend(_LATIN_RUN.findall(t["text"].lower()))
    return words


def _is_switch(prev: str, curr: str) -> bool:
    return (prev == "thai" and curr == "latin") or (prev == "latin" and curr == "thai")


def _char_script(c: str) -> str | None:
    if _THAI_CHAR.match(c):
        return "thai"
    if c.isascii() and c.isalpha():
        return "latin"
    return None


def _switch_points(tokens: list[dict]) -> list[float]:
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
    matched = _match_points(ref_pts, hyp_pts, tol_ms)
    return boundary_f1_error(matched, len(ref_pts), len(hyp_pts)), matched


def _cue_starts(tokens: list[dict]) -> list[float]:
    return [float(t["start_ms"]) for t in tokens if t.get("start_ms") is not None]


def _cue_overlap_count(tokens: list[dict]) -> int:
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


def _speech_coverage(ref_tokens: list[dict], hyp_tokens: list[dict]) -> tuple[float, float]:
    def spans(tokens: list[dict]) -> list[tuple[float, float]]:
        return [(float(t["start_ms"]), float(t["end_ms"])) for t in tokens
                if t.get("start_ms") is not None and t.get("end_ms") is not None]

    hyp = spans(hyp_tokens)
    total = missed = 0.0
    for start, end in spans(ref_tokens):
        dur = max(0.0, end - start)
        total += dur
        if not any(hs < end and he > start for hs, he in hyp):
            missed += dur
    return total, missed


def _orphan_count(tokens: list[dict]) -> int:
    spans = [(float(t["start_ms"]), float(t["end_ms"])) for t in tokens
             if t.get("start_ms") is not None and t.get("end_ms") is not None]
    count = 0
    for i, (start, end) in enumerate(spans):
        if end - start >= ORPHAN_MAX_MS:
            continue
        before = start - spans[i - 1][1] if i > 0 else float("inf")
        after = spans[i + 1][0] - end if i + 1 < len(spans) else float("inf")
        if before >= ORPHAN_ISOLATION_MS and after >= ORPHAN_ISOLATION_MS:
            count += 1
    return count


CI_METRICS = ("cer_thai", "wer_latin", "boundary_error_rate", "cue_boundary_error_rate",
              "speech_coverage_miss")


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
    corpus aggregate each draw via `EvalMetrics.aggregate` — the same rule the
    point estimate is computed by, so the two can never measure different
    quantities. `seed` defaults to a fixed value so re-running the harness
    against an unchanged hypothesis reproduces the same band (Phase A's
    acceptance check: "a re-run of the baseline reproduces within CI"); pass
    `seed=None` for a fresh draw each call.
    """
    n = len(clip_metrics)
    if n == 0:
        return (0.0, 0.0)
    rng = random.Random(seed)
    draws = sorted(
        getattr(EvalMetrics.aggregate([clip_metrics[rng.randrange(n)] for _ in range(n)]), metric)
        for _ in range(n_draws)
    )
    lo = draws[int((1 - ci) / 2 * n_draws)]
    hi = draws[min(n_draws - 1, int((1 + ci) / 2 * n_draws))]
    return lo, hi


def paired_bootstrap_ci(
    candidate: list[EvalMetrics], baseline: list[EvalMetrics], metric: str,
    n_draws: int = 1000, ci: float = 0.95, seed: int | None = 0,
) -> tuple[float, float]:
    """CI of candidate minus baseline; matching clip order is required.

    Both corpora use the SAME sampled indices and their own aggregate counts.
    This retains reference weighting and micro-F1, including hallucinated
    boundaries on clips with no reference boundaries. Lower deltas are better.
    """
    if not candidate or len(candidate) != len(baseline):
        raise ValueError("paired bootstrap requires nonempty, equally sized corpora")
    if metric not in CI_METRICS or n_draws < 1 or not 0 < ci < 1:
        raise ValueError("invalid metric, draw count or confidence level")
    rng = random.Random(seed)
    draws = []
    for _ in range(n_draws):
        indices = [rng.randrange(len(candidate)) for _ in candidate]
        now = EvalMetrics.aggregate([candidate[i] for i in indices])
        base = EvalMetrics.aggregate([baseline[i] for i in indices])
        draws.append(getattr(now, metric) - getattr(base, metric))
    draws.sort()
    return (draws[int((1 - ci) / 2 * n_draws)],
            draws[min(n_draws - 1, int((1 + ci) / 2 * n_draws))])


def _normalize_tokens(tokens: list[dict], config: dict) -> list[dict]:
    from transcribe.pipeline.normalize import normalize
    out = []
    for t in tokens:
        nt = dict(t)
        nt["text"] = normalize(t["text"], config)
        out.append(nt)
    return out


def compute_metrics(
    ref_tokens: list[dict],
    hyp_tokens: list[dict],
    config: dict | None = None,
    boundary_tol_ms: float = 300.0,
) -> EvalMetrics:
    if config is not None:
        ref_tokens = _normalize_tokens(ref_tokens, config)
        hyp_tokens = _normalize_tokens(hyp_tokens, config)

    ref_thai = _thai_char_stream(ref_tokens)
    hyp_thai = _thai_char_stream(hyp_tokens)
    cer_thai = _error_rate(ref_thai, hyp_thai)

    ref_latin = _latin_word_stream(ref_tokens)
    hyp_latin = _latin_word_stream(hyp_tokens)
    wer_latin = _error_rate(ref_latin, hyp_latin)

    ref_pts = _switch_points(ref_tokens)
    hyp_pts = _switch_points(hyp_tokens)
    ber, matched = _temporal_boundary_error(ref_pts, hyp_pts, boundary_tol_ms)

    ref_words = [t["text"] for t in ref_tokens]
    hyp_words = [t["text"] for t in hyp_tokens]
    overall_wer = _error_rate(ref_words, hyp_words)

    ref_cue_pts = _cue_starts(ref_tokens)
    hyp_cue_pts = _cue_starts(hyp_tokens)
    cue_matched = _match_points(ref_cue_pts, hyp_cue_pts, boundary_tol_ms)
    cue_ber = boundary_f1_error(cue_matched, len(ref_cue_pts), len(hyp_cue_pts))
    overlapping_cues = _cue_overlap_count(hyp_tokens)
    shortest_cue_ms, nonzero_gap_count = _cue_gap_stats(hyp_tokens)
    ref_speech_ms, missed_speech_ms = _speech_coverage(ref_tokens, hyp_tokens)

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
        speech_coverage_miss=missed_speech_ms / ref_speech_ms if ref_speech_ms else 0.0,
        ref_speech_ms=ref_speech_ms,
        missed_speech_ms=missed_speech_ms,
        orphan_cues=_orphan_count(hyp_tokens),
    )
