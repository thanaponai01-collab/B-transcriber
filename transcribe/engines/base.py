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

    @abstractmethod
    def unload(self) -> None:
        """Release model weights and free VRAM/RAM."""
