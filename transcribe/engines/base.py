"""Abstract Engine base class."""

from __future__ import annotations

import gc
import logging
from abc import ABC, abstractmethod

from transcribe.contracts import EngineInput, EngineResult

logger = logging.getLogger(__name__)


class Engine(ABC):
    """All ASR engine adapters must subclass this.

    VRAM teardown (issue #11) lives here, concrete, so every adapter gets it
    by subclassing rather than by copying a neighbour's `unload()`: drop
    handles -> gc.collect() -> torch.cuda.empty_cache(). That order is part
    of the contract, not an accident — torch.cuda.empty_cache() only returns
    blocks the allocator has already freed, and if a Python reference cycle
    is still holding the model, a bare `del` hasn't freed it yet;
    gc.collect() breaks those cycles first so empty_cache() has something to
    release. Adapters never override `unload()` itself — they override
    `_release()` to drop their own handles (and anything else genuinely
    theirs, e.g. faster_whisper's CUDA-DLL PATH restore). The gc/empty_cache
    half of the ritual is never an adapter's to forget.
    """

    # Whole-file engines (CTranslate2 / faster-whisper) do their own internal VAD
    # and segmentation and are crippled by per-chunk feeding (per-call overhead +
    # an alignment pass per chunk). When True, the pipeline hands the engine the
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

        Override when the backend supports batched GPU inference — that's where
        the real throughput win is, since it replaces N separate forward passes
        with ceil(N / batch_size) of them.
        """
        return [self.transcribe(inp) for inp in inputs]

    def _load_array(self, inp: EngineInput):
        """Use the pre-decoded array when given one (skips a disk round-trip)."""
        if inp.audio is not None:
            return inp.audio
        import librosa
        audio, _ = librosa.load(inp.audio_path, sr=16000, mono=True)
        return audio

    def _release(self) -> None:
        """Drop this adapter's own handles. No-op by default — correct for
        `mock` and `passthrough`, which hold nothing to release.

        Override this, not `unload()`, to `del` model/pipeline/processor
        handles and to do anything else that is genuinely this adapter's own
        obligation (e.g. faster_whisper restoring the PATH it mutated to
        load CUDA-12 DLLs). Do not call gc.collect() or
        torch.cuda.empty_cache() here — unload() already does, in the order
        that makes them effective. End with this adapter's own log line so
        job-log `[VRAM]` traces stay attributable to a named engine.
        """

    def unload(self) -> None:
        """Release model weights and free VRAM/RAM.

        Safe to call on an engine that was never loaded (a failed load() in
        a try block) and safe to call twice (a resumed or aborted job) — a
        no-op `_release()` and idempotent gc/empty_cache calls make both
        harmless. A `_release()` that raises is logged, not swallowed, but
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

        # Imported here, not at module scope: base.py is imported by
        # registry.py, which the pipeline imports just to answer
        # prefers_whole_file() without instantiating anything. A module-level
        # torch import would pull the GPU stack into every code path that
        # merely asks a capability question. Wrapped exactly as typhoon_rt's
        # own unload() already did: mock/passthrough tear down through this
        # same path and must stay usable even where torch isn't importable.
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
