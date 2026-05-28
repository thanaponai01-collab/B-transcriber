"""Flywheel Phase 9a — diff raw ASR output vs human corrections → correction pairs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CorrectionPair:
    token_idx: int
    raw_text: str
    corrected_text: str
    source_engine: str


def diff_corrections(
    original_tokens: list[dict],   # from DB: {"idx", "text", "source_engine", ...}
    corrected_tokens: list[dict],  # from editor: {"idx", "text", ...}
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
            ))
    return pairs
