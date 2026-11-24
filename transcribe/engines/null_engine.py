from __future__ import annotations

from transcribe.contracts import EngineInput, EngineResult
from transcribe.engines.base import Engine
from transcribe.engines.registry import register


@register("passthrough")
class NullEngine(Engine):
    def __init__(self, **kwargs):
        pass

    def load(self) -> None:
        pass

    def transcribe(self, inp: EngineInput) -> EngineResult:
        return EngineResult(tokens=[], engine_name="null", raw={})
