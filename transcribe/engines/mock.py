"""MockEngine — returns canned tokens; lets the full pipeline run without a real model."""

from __future__ import annotations

from transcribe.contracts import EngineInput, EngineResult, RecognizedToken
from transcribe.engines.base import Engine
from transcribe.engines.registry import register


@register("mock")
class MockEngine(Engine):
    """Deterministic mock for testing. Returns predictable tokens from the audio path."""

    def __init__(self, name: str = "mock", lang: str = "th", **kwargs):
        # **kwargs so config-driven per-engine overrides (device, compute_type, …)
        # never break the test engine (2.3).
        self._name = name
        self._lang = lang
        self._loaded = False

    def load(self) -> None:
        self._loaded = True

    def transcribe(self, inp: EngineInput) -> EngineResult:
        assert self._loaded, "load() must be called before transcribe()"
        # Produce 5 synthetic tokens spanning 0–5 seconds
        tokens = [
            RecognizedToken(text="สวัสดี", start_ms=0,    end_ms=500,  confidence=0.95, script="thai"),
            RecognizedToken(text="ครับ",   start_ms=500,  end_ms=900,  confidence=0.90, script="thai"),
            RecognizedToken(text="Hello",  start_ms=1000, end_ms=1400, confidence=0.88, script="latin"),
            RecognizedToken(text="world",  start_ms=1400, end_ms=1800, confidence=0.85, script="latin"),
            RecognizedToken(text="นะ",    start_ms=1800, end_ms=2000, confidence=0.92, script="thai"),
        ]
        return EngineResult(
            tokens=tokens,
            engine_name=self._name,
            timestamps_final=True,
            raw={"mock": True, "audio_path": inp.audio_path},
        )

    def unload(self) -> None:
        self._loaded = False
