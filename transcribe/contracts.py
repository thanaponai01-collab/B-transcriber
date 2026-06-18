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
    word_level_timestamps: bool = False  # True when engine returned per-word spans
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
