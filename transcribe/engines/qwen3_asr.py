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

Timestamps (revised 2026-08-05, see TODO_LEDGER "Qwen3-ASR internal VAD
chunking fix"): the original design emitted ONE whole-clip token at a
placeholder start_ms=0/end_ms=0 and deferred real timestamps to the
pipeline's forced-alignment pass. That's incompatible with the actual
pipeline order in CLAUDE.md: `align_hyp.py` (hypothesis-to-hypothesis
alignment, purely a temporal-window match — see its `_MATCH_PROX_MS`/
`_token_overlap_ms`) runs BEFORE reconciliation, and forced alignment runs
AFTER. A zero-duration token at t=0 can only even be considered against
Engine A tokens starting in the first ~1.5s of a clip, so on any real
multi-cue file this engine was a silent no-op — confirmed by a harness probe
coming back byte-identical to the passthrough baseline on every metric.
Fixed by giving this `prefers_whole_file=True` engine the same contract
faster_whisper's adapter already satisfies: do its own internal VAD
(via the shared `transcribe.audio.speech_windows` seam, no new dependency
and no reach into another adapter) and
emit one token per real speech span with genuine span-derived start_ms/
end_ms, so `timestamps_final=True`. A file with no detected speech (or
audio_path-only calls, which can't be VAD'd without a decoded array) falls
back to a single whole-clip span, matching the old shape but with a real
(0, duration) timestamp instead of (0, 0). Wiring the companion
`Qwen3-ForcedAligner-0.6B` for word-level timestamps remains a possible
future upgrade, not required now that span-level timestamps make this
engine align-able at all.

confidence is never faked: this engine reports None, same discipline as every
other adapter.

VRAM: 1.7B in bf16 is a few GB, comfortably inside the 8GB ceiling loaded alone.
Engine A is unloaded before this loads — never assume shared VRAM.
"""

from __future__ import annotations

import logging

import torch

from transcribe.audio import WindowPolicy, speech_windows
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
        vad_threshold: float = 0.35,
        vad_min_silence_ms: int = 500,
        max_span_s: float = 8.0,
    ):
        self._model_id = model_id
        self._device = device
        self._max_inference_batch_size = max_inference_batch_size
        self._max_new_tokens = max_new_tokens
        # Deliberately NOT faster-whisper's policy — see _speech_spans_s for the
        # max_span_s reasoning, and note two further differences that are
        # decisions, not oversights:
        #   overlap_s=0.0        — this engine has no seam-dedupe pass, so an
        #                          overlap would duplicate text in the output.
        #   merge_max_gap_s=None — no zero-gap span merge. Preserves the exact
        #                          behaviour this adapter has always had (it only
        #                          ever imported two of faster-whisper's three
        #                          windowing steps). Enabling it is a behaviour
        #                          change that must be harness-probed on its own,
        #                          not smuggled in under a refactor.
        # `None` is not `0.0`: a reported gap of exactly 0.0 is the common case
        # the merge exists to catch, so 0.0 would still merge. See WindowPolicy.
        self._window_policy = WindowPolicy(
            vad_threshold=vad_threshold,
            vad_min_silence_ms=vad_min_silence_ms,
            merge_max_gap_s=None,
            max_span_s=max_span_s,
            overlap_s=0.0,
            whole_clip_on_silence=True,
        )
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
        """Single-token, unknown-timestamp shape — only used when there's no
        decoded audio array to VAD (audio_path-only calls; the pipeline never
        does this for a prefers_whole_file engine, see
        pipeline/engine_run.py's _transcribe_with, so this is a
        testing/legacy path only)."""
        text = (text or "").strip()
        if not text:
            return []
        return [RecognizedToken(
            text=text, start_ms=0, end_ms=0, confidence=None, script=detect_script(text),
        )]

    def _speech_spans_s(self, audio) -> list[tuple[float, float]]:
        """Real speech spans (seconds) via the shared windowing seam
        (`transcribe.audio.speech_windows`). Falls back to one whole-clip span
        when VAD finds nothing (silence, or a clip too short/quiet for Silero to
        fire) so the engine still emits something — that is
        `whole_clip_on_silence` on this engine's policy.

        `max_span_s` (default 8.0, NOT faster_whisper's 25s `_LONG_SPAN_SAFE_S`
        — 2026-08-xx, see TODO_LEDGER "Qwen3-ASR span-granularity fix"): a
        real-disagreement instrumentation pass showed every single
        _script_fallback disagreement on the gold set was Engine A's short
        (~2-5s, cue_target_chars=42) phrase cue vs a single Qwen3-ASR token
        spanning up to 25s / a whole multi-sentence VAD segment — never a
        comparable head-to-head. align_hyp.py matches each short A cue against
        whichever B token's time window overlaps it, so every A cue in a long
        span was being compared against the SAME giant multi-sentence B blob.
        No reconciler tiebreak logic can fix a candidate-set mismatch this
        coarse; the fix has to be at the source — cap B's span length so its
        tokens are close enough in scale to A's phrase cues for a real
        head-to-head. 8.0s is a starting point (roughly 2-3x a typical A cue,
        not 1:1 — Qwen3-ASR is an LLM-decoder model that likely benefits from
        more context than a single short cue), tunable via config."""
        return [(w.start_s, w.end_s) for w in speech_windows(audio, self._window_policy)]

    def transcribe(self, inp: EngineInput) -> EngineResult:
        assert self._model is not None, "load() must be called first"
        context = self._context_arg(inp.bias_terms)
        language = self._language_arg(inp.language_hint)

        if inp.audio is None:
            # No decoded array to VAD — e.g. audio_path-only calls.
            results = self._model.transcribe(audio=self._audio_arg(inp), context=context, language=language)
            result = results[0]
            text = getattr(result, "text", "") or ""
            return EngineResult(
                tokens=self._result_to_tokens(text),
                engine_name="qwen3_asr",
                timestamps_final=False,
                raw={"language": getattr(result, "language", None), "text": text},
            )

        spans = self._speech_spans_s(inp.audio)
        whole_clip = len(spans) == 1 and spans[0] == (0.0, len(inp.audio) / _SAMPLE_RATE)
        slices = [inp.audio] if whole_clip else [
            inp.audio[int(s * _SAMPLE_RATE):int(e * _SAMPLE_RATE)] for s, e in spans
        ]

        if len(slices) == 1:
            results = self._model.transcribe(audio=(slices[0], _SAMPLE_RATE), context=context, language=language)
        else:
            results = self._model.transcribe(
                audio=[(a, _SAMPLE_RATE) for a in slices],
                context=[context] * len(slices),
                language=[language] * len(slices),
            )

        tokens: list[RecognizedToken] = []
        texts: list[str] = []
        languages: list[str] = []
        for (start_s, end_s), r in zip(spans, results):
            text = (getattr(r, "text", "") or "").strip()
            texts.append(text)
            languages.append(getattr(r, "language", None))
            if not text:
                continue
            tokens.append(RecognizedToken(
                text=text, start_ms=int(start_s * 1000), end_ms=int(end_s * 1000),
                confidence=None, script=detect_script(text),
            ))
        return EngineResult(
            tokens=tokens,
            engine_name="qwen3_asr",
            timestamps_final=True,
            raw={"language": languages[0] if languages else None, "text": " ".join(t for t in texts if t)},
        )

    def transcribe_batch(self, inputs: list[EngineInput], batch_size: int = 8) -> list[EngineResult]:
        """Delegates to transcribe() per input so every call gets the same
        internal-VAD real-timestamp treatment. qwen_asr batches internally via
        max_inference_batch_size (set at load time) rather than a per-call
        batch_size knob, and this engine is prefers_whole_file=True so the
        pipeline never actually calls transcribe_batch — kept for adapter-
        contract completeness (an OOM here is a real failure, not a backoff
        opportunity, since there's no batch_size to retry smaller at)."""
        assert self._model is not None, "load() must be called first"
        return [self.transcribe(inp) for inp in inputs]

    def unload(self) -> None:
        if self._model is not None:
            del self._model
            self._model = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("Qwen3-ASR unloaded, VRAM freed")
