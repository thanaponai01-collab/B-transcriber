"""Engine B candidate — Qwen3-ASR, LLM-decoder ASR for the code-switch wall.

HANDOFF_CEILING_BREAK.md §6/4.1: unlike every prior Engine-B candidate (funasr,
typhoon_rt, whisper_multi — all rejected, see config.yaml's engine_b comment),
Qwen3-ASR's decoder *is* a language model, so intra-sentential Thai<->English
switching is a semantic prediction rather than an acoustic-only guess. This
targets the two metrics every prior candidate left dead: wer_latin and BER.

Uses the `qwen_asr` package (`Qwen3ASRModel.from_pretrained(...).transcribe(...)`),
not the transformers pipeline other adapters share — Qwen3-ASR ships its own
inference wrapper. See https://huggingface.co/Qwen/Qwen3-ASR-1.7B. Verified
against the installed package (0.0.6) via introspection, not just the model
card: `transcribe()` accepts `audio` as a path/URL string OR an
`(np.ndarray, sample_rate)` tuple (or a list of either) — no temp-file
round-trip is needed for pre-decoded audio, unlike the transformers-pipeline
engines. It also takes a `context: str` argument (a free-text hint merged into
the model's prompt), which this adapter uses for `EngineInput.bias_terms` via
the same `flywheel.inject.build_prompt` budget-packing every other engine's
bias injection uses — GAP-5's mechanism, this engine's own slot.

Timestamps: start with `timestamps_final=False` and let the pipeline's existing
forced-alignment path assign real ms values (the smaller diff per the handoff) —
wiring the companion `Qwen3-ForcedAligner-0.6B` (`transcribe(..., return_time_stamps=True)`,
requires passing `forced_aligner=` at `from_pretrained` time) is a later,
separate probe, not part of this first cut.

confidence is never faked: this engine reports None, same discipline as every
other adapter.

VRAM: 1.7B in bf16 is a few GB, comfortably inside the 8GB ceiling loaded alone.
Engine A is unloaded before this loads — never assume shared VRAM.
"""

from __future__ import annotations

import logging

import torch

from transcribe.contracts import EngineInput, EngineResult, RecognizedToken, detect_script
from transcribe.engines.base import Engine
from transcribe.engines.registry import register
from transcribe.flywheel.inject import BiasTerm, build_prompt

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "Qwen/Qwen3-ASR-1.7B"
_SAMPLE_RATE = 16000

# qwen_asr's `language` argument takes full names, not ISO codes.
_LANGUAGE_NAMES = {"th": "Thai", "en": "English"}


@register("qwen3_asr")
class Qwen3ASREngine(Engine):
    """LLM-decoder ASR — code-switch Engine B candidate."""

    prefers_whole_file = True

    def __init__(
        self,
        model_id: str = _DEFAULT_MODEL,
        device: str = "cuda",
        max_inference_batch_size: int = 8,
        max_new_tokens: int = 256,
    ):
        self._model_id = model_id
        self._device = device
        self._max_inference_batch_size = max_inference_batch_size
        self._max_new_tokens = max_new_tokens
        self._model = None

    def load(self) -> None:
        from qwen_asr import Qwen3ASRModel

        logger.info("Loading Qwen3-ASR: %s", self._model_id)
        dtype = torch.bfloat16 if self._device != "cpu" else torch.float32
        self._model = Qwen3ASRModel.from_pretrained(
            self._model_id,
            dtype=dtype,
            device_map=self._device,
            max_inference_batch_size=self._max_inference_batch_size,
            max_new_tokens=self._max_new_tokens,
        )
        logger.info("Qwen3-ASR loaded on %s", self._device)

    def _audio_arg(self, inp: EngineInput):
        """qwen_asr accepts a path string or an (array, sample_rate) tuple directly."""
        if inp.audio_path is not None:
            return inp.audio_path
        return (inp.audio, _SAMPLE_RATE)

    def _language_arg(self, language_hint: str | None):
        if not language_hint:
            return None
        return _LANGUAGE_NAMES.get(language_hint, language_hint)

    def _context_arg(self, bias_terms: list[str]) -> str:
        """Pack bias terms into the model's `context` prompt slot (GAP-5)."""
        if not bias_terms:
            return ""
        return build_prompt([BiasTerm(t) for t in bias_terms])

    def _result_to_tokens(self, text: str) -> list[RecognizedToken]:
        text = (text or "").strip()
        if not text:
            return []
        # Whole-clip placeholder span — timestamps_final=False means align_force's
        # forced-alignment pass replaces these with real ms values.
        return [RecognizedToken(
            text=text, start_ms=0, end_ms=0, confidence=None, script=detect_script(text),
        )]

    def transcribe(self, inp: EngineInput) -> EngineResult:
        assert self._model is not None, "load() must be called first"
        results = self._model.transcribe(
            audio=self._audio_arg(inp),
            context=self._context_arg(inp.bias_terms),
            language=self._language_arg(inp.language_hint),
        )

        result = results[0]
        text = getattr(result, "text", "") or ""
        return EngineResult(
            tokens=self._result_to_tokens(text),
            engine_name="qwen3_asr",
            timestamps_final=False,
            raw={"language": getattr(result, "language", None), "text": text},
        )

    def transcribe_batch(self, inputs: list[EngineInput], batch_size: int = 8) -> list[EngineResult]:
        """qwen_asr batches internally via max_inference_batch_size (set at load
        time); there's no per-call batch_size knob to retry at on OOM the way the
        HF-pipeline engines do, so an OOM here is a real failure, not a backoff
        opportunity — it surfaces to the caller.
        """
        assert self._model is not None, "load() must be called first"
        if not inputs:
            return []

        audios = [self._audio_arg(inp) for inp in inputs]
        contexts = [self._context_arg(inp.bias_terms) for inp in inputs]
        languages = [self._language_arg(inp.language_hint) for inp in inputs]
        results = self._model.transcribe(audio=audios, context=contexts, language=languages)

        out: list[EngineResult] = []
        for r in results:
            text = getattr(r, "text", "") or ""
            out.append(EngineResult(
                tokens=self._result_to_tokens(text),
                engine_name="qwen3_asr",
                timestamps_final=False,
                raw={"language": getattr(r, "language", None), "text": text},
            ))
        return out

    def unload(self) -> None:
        if self._model is not None:
            del self._model
            self._model = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("Qwen3-ASR unloaded, VRAM freed")
