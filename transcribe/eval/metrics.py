"""WER and code-switch boundary error rate."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EvalMetrics:
    wer: float
    boundary_error_rate: float
    total_words: int
    boundary_words: int


def _edit_distance(ref: list[str], hyp: list[str]) -> int:
    """Levenshtein distance between two word lists."""
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


def word_error_rate(reference: list[str], hypothesis: list[str]) -> float:
    if not reference:
        return 0.0 if not hypothesis else 1.0
    return _edit_distance(reference, hypothesis) / len(reference)


def _boundary_indices(tokens: list[dict]) -> set[int]:
    """Return indices of tokens that are within 2 positions of a script boundary."""
    boundary_positions = set()
    scripts = [t["script"] for t in tokens]
    for i in range(1, len(scripts)):
        prev = scripts[i - 1]
        curr = scripts[i]
        is_transition = (
            (prev == "thai" and curr == "latin")
            or (prev == "latin" and curr == "thai")
        )
        if is_transition:
            for offset in range(-2, 3):
                idx = i + offset
                if 0 <= idx < len(scripts):
                    boundary_positions.add(idx)
    return boundary_positions


def compute_metrics(
    ref_tokens: list[dict],  # list of {"text": str, "script": str}
    hyp_tokens: list[dict],
) -> EvalMetrics:
    ref_words = [t["text"] for t in ref_tokens]
    hyp_words = [t["text"] for t in hyp_tokens]

    overall_wer = word_error_rate(ref_words, hyp_words)

    # Boundary error rate: only words near a script boundary in the reference
    boundary_idx = _boundary_indices(ref_tokens)
    if not boundary_idx:
        ber = 0.0
        boundary_count = 0
    else:
        ref_boundary = [ref_words[i] for i in sorted(boundary_idx)]
        # Align hypothesis to reference indices; use the same indices if available
        hyp_boundary = [hyp_words[i] if i < len(hyp_words) else "" for i in sorted(boundary_idx)]
        ber = word_error_rate(ref_boundary, hyp_boundary)
        boundary_count = len(boundary_idx)

    return EvalMetrics(
        wer=overall_wer,
        boundary_error_rate=ber,
        total_words=len(ref_words),
        boundary_words=boundary_count,
    )
