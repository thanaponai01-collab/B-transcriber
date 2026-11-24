from __future__ import annotations

import gc
import logging
from abc import ABC, abstractmethod

from transcribe.contracts import EngineInput, EngineResult

logger = logging.getLogger(__name__)


class Engine(ABC):
    """Drop handles -> gc.collect() -> torch.cuda.empty_cache(). torch.cuda.empty_cache() only returns
    blocks the allocator has already freed, and if a Python reference cycle
    is still holding the model, a bare `del` hasn't freed it yet;
    gc.collect() breaks those cycles first so empty_cache() has something to
    release.
    """

    # When True, the pipeline hands the engine the
    # full audio in one call and trusts its absolute timestamps.
    prefers_whole_file: bool = False

    @abstractmethod
    def load(self) -> None:
        """Load model weights into memory."""

    @abstractmethod
    def transcribe(self, inp: EngineInput) -> EngineResult:
        """Transcribe audio. Engine must be loaded first."""

    def transcribe_batch(self, inputs: list[EngineInput], batch_size: int = 8) -> list[EngineResult]:
        """Transcribe many inputs, in order. Default: one transcribe() call per input.

        Override when the backend supports batched GPU inference.
        """
        return [self.transcribe(inp) for inp in inputs]

    def _load_array(self, inp: EngineInput):
        if inp.audio is not None:
            return inp.audio
        import librosa
        audio, _ = librosa.load(inp.audio_path, sr=16000, mono=True)
        return audio

    def _release(self) -> None:
        """Drop this adapter's own handles. No-op by default.

        Override this, not `unload()`, to `del` model/pipeline/processor
        handles and to do anything else that is genuinely this adapter's own
        obligation. Do not call gc.collect() or
        torch.cuda.empty_cache() here — unload() already does. End with this adapter's own log line so
        job-log `[VRAM]` traces stay attributable to a named engine.
        """

    def unload(self) -> None:
        """Release model weights and free VRAM/RAM.

        Safe to call on an engine that was never loaded and safe to call twice.
        A `_release()` that raises is logged, not swallowed, but
        never strands the card: gc.collect() and empty_cache() still run.
        """
        try:
            self._release()
        except Exception:
            logger.exception(
                "%s._release() raised during unload() — VRAM teardown continues",
                type(self).__name__,
            )

        gc.collect()

        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
