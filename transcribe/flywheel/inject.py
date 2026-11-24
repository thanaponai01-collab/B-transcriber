from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_THAI_LO, _THAI_HI = "฀", "๿"
_BUDGET_TOKENS = 200


@dataclass
class BiasTerm:
    term: str
    weight: float = 1.0
    recency: float = 1.0


def _approx_tokens(text: str) -> int:
    thai = sum(1 for c in text if _THAI_LO <= c <= _THAI_HI)
    nonthai = "".join(" " if _THAI_LO <= c <= _THAI_HI else c for c in text)
    words = len(nonthai.split())
    return thai + words


def build_prompt(
    terms: list[BiasTerm],
    budget_tokens: int = 200,
    count_tokens: Optional[Callable[[str], int]] = None,
) -> str:
    """Greedily pack bias terms into ``budget_tokens``, highest value first.

    Ordering is ``weight * recency`` descending. Packing is greedy: a term is
    included only if it still fits the budget, but a later, cheaper term may slot
    into leftover space after a costlier one is skipped — so the prompt is filled,
    not abandoned at the first term that does not fit.

    Returns a single space-joined string (Thai terms joined with spaces
    deliberately — prompt-only, never the output's normalized form).
    """
    count = count_tokens or _approx_tokens
    ranked = sorted(terms, key=lambda t: t.weight * t.recency, reverse=True)

    chosen: list[str] = []
    used = 0
    for t in ranked:
        cost = count(t.term)
        sep = 1 if chosen else 0
        if used + sep + cost <= budget_tokens:
            chosen.append(t.term)
            used += sep + cost
    return " ".join(chosen)


def build_prompt_ids(processor, device: str, bias_terms: list[str],
                     budget_tokens: int = _BUDGET_TOKENS):
    """Build Whisper prompt_ids from bias terms within the token budget (GAP-5).

    Shared by both Whisper engine adapters — each just supplies its own
    processor/device. ``budget_tokens`` comes from config.flywheel.bias_prompt_budget
    when the engine threads it through; defaults to _BUDGET_TOKENS otherwise.
    Non-fatal: a prompt failure must never block ASR.
    """
    if not bias_terms:
        return None
    try:
        tok = processor.tokenizer
        prompt = build_prompt(
            [BiasTerm(t) for t in bias_terms],
            budget_tokens=budget_tokens,
            count_tokens=lambda s: len(tok(s, add_special_tokens=False).input_ids),
        )
        if not prompt:
            return None
        return processor.get_prompt_ids(prompt, return_tensors="pt").to(device)
    except Exception as e:
        logger.warning("Bias prompt injection skipped (%s)", e)
        return None
