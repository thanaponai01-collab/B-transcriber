"""Engine Contract — the durable interface between the pipeline and ASR models.

Every ASR model is accessed ONLY through these dataclasses.
No component outside engines/ may import a concrete model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EngineInput:
    audio_path: str
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
    raw: dict = field(default_factory=dict)  # untouched native output, for debugging
