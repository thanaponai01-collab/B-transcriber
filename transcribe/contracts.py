"""Engine Contract — the durable interface between the pipeline and ASR models.

Every ASR model is accessed ONLY through these dataclasses.
No component outside engines/ may import a concrete model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np


def detect_script(text: str) -> str:
    """Classify text as 'thai' | 'latin' | 'mixed' | 'other'."""
    thai = sum(1 for c in text if "฀" <= c <= "๿")
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    if thai and not latin:
        return "thai"
    if latin and not thai:
        return "latin"
    if thai and latin:
        return "mixed"
    return "other"


@dataclass
class EngineInput:
    audio_path: Optional[str] = None
    audio: Optional[np.ndarray] = None  # pre-decoded 16kHz mono float32; skips disk I/O if set
    bias_terms: list[str] = field(default_factory=list)
    # {term: weight} for budget-aware prompt ranking (5.1). Optional — engines that
    # ignore it fall back to unit weight (insertion order).
    bias_weights: dict = field(default_factory=dict)
    language_hint: Optional[str] = None  # "th", "en", or None


@dataclass
class RecognizedToken:
    text: str
    start_ms: int
    end_ms: int
    confidence: Optional[float]  # None if engine gives none — do NOT fake it
    script: str                  # thai | latin | other | mixed


@dataclass
class EngineResult:
    tokens: list[RecognizedToken]
    engine_name: str
    # True ⇒ these tokens carry final timestamps; the pipeline skips forced
    # alignment and word expansion. (Renamed from word_level_timestamps: the
    # faster-whisper tokens are phrase cues with final timestamps, not words —
    # word granularity is re-derived on demand from `raw`. See CLAUDE.md 5.4.)
    timestamps_final: bool = False
    raw: dict = field(default_factory=dict)  # untouched native output, for debugging


@dataclass
class PipelineToken:
    """Typed token flowing through the post-reconcile pipeline stages."""
    idx: int
    text: str
    start_ms: int
    end_ms: int
    script: str           # thai | latin | other | mixed
    confidence: Optional[float]
    source_engine: str    # 'a' | 'b' | 'both'
