"""Abstract Engine base class."""

from __future__ import annotations

from abc import ABC, abstractmethod

from transcribe.contracts import EngineInput, EngineResult


class Engine(ABC):
    """All ASR engine adapters must subclass this."""

    @abstractmethod
    def load(self) -> None:
        """Load model weights into memory."""

    @abstractmethod
    def transcribe(self, inp: EngineInput) -> EngineResult:
        """Transcribe audio. Engine must be loaded first."""

    def transcribe_batch(self, inputs: list[EngineInput], batch_size: int = 8) -> list[EngineResult]:
        """Transcribe many inputs, in order. Default: one transcribe() call per input.

        Override when the backend supports batched GPU inference — that's where
        the real throughput win is, since it replaces N separate forward passes
        with ceil(N / batch_size) of them.
        """
        return [self.transcribe(inp) for inp in inputs]

    @abstractmethod
    def unload(self) -> None:
        """Release model weights and free VRAM/RAM."""
