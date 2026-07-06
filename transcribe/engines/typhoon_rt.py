"""Engine B candidate — Typhoon ASR Real-time (FastConformer-Transducer).

arXiv 2601.13044 (SCB10X/Typhoon, Jan 2026). ~115M params, ~45× lower compute than
Whisper large-v3 at comparable Thai CER. The point is *decorrelation*: a transducer
(frame-synchronous, monotonic) has different failure modes than Whisper's seq2seq,
and it structurally cannot hallucinate repetition loops — so cross-engine agreement
finally becomes a real confidence signal.

Runs via NVIDIA NeMo (`nemo_toolkit[asr]`). NeMo is imported inside load() so the
heavy stack is touched only when this engine is actually selected — everything else
(the faster_whisper default path, all tests) stays clean if NeMo is absent.

STATUS: NeMo's Python 3.13 wheel situation is unverified (this is what killed FunASR;
nemo_toolkit 2.7.x is on PyPI but its ASR extra pulls a large C-dep tree). Activation
is eval-gated anyway (engine_b stays `passthrough` until the gold set proves this
lowers cer_thai/BER — handoff 4.2). See TODO_LEDGER.

Contract discipline: confidence is None (transducers give no usable per-token
confidence — never faked). Output is verbatim model text; normalize.py remains the
single normalization authority and runs after reconciliation — no compensation here.
"""

from __future__ import annotations

import gc
import logging

from transcribe.contracts import EngineInput, EngineResult, RecognizedToken, detect_script
from transcribe.engines.base import Engine
from transcribe.engines.registry import register

logger = logging.getLogger(__name__)

# NGC/HF id of the released model. Override via config["engines"]["typhoon_rt"].
_DEFAULT_MODEL = "scb10x/typhoon-asr-realtime"


@register("typhoon_rt")
class TyphoonRTEngine(Engine):
    """FastConformer-Transducer Thai ASR via NeMo. Whole-file: the model is cheap
    enough that segmenting buys nothing, and whole-file gives absolute timestamps
    the reconciler can align against Engine A's cues."""

    prefers_whole_file = True

    def __init__(self, model_id: str = _DEFAULT_MODEL, device: str = "cuda", **kwargs):
        self._model_id = model_id
        self._device = device
        self._model = None

    def load(self) -> None:
        # Imported here so the NeMo stack is only required when this engine runs.
        from nemo.collections.asr.models import ASRModel

        logger.info("Loading Typhoon RT (NeMo): %s", self._model_id)
        self._model = ASRModel.from_pretrained(model_name=self._model_id)
        self._model = self._model.to(self._device).eval()
        logger.info("Typhoon RT loaded on %s", self._device)

    def transcribe(self, inp: EngineInput) -> EngineResult:
        assert self._model is not None, "load() must be called first"
        audio = self._load_array(inp)
        audio_ms = int(len(audio) * 1000 / 16000)

        # NeMo transcribe with word timestamps. API shape varies across NeMo
        # versions; _hyp_to_tokens is defensive about what it gets back.
        hyps = self._model.transcribe([audio], timestamps=True)
        hyp = hyps[0] if isinstance(hyps, (list, tuple)) and hyps else hyps
        tokens = _hyp_to_tokens(hyp, audio_ms)

        return EngineResult(
            tokens=tokens,
            engine_name="typhoon_rt",
            timestamps_final=True,   # token-level timestamps are final; skip re-align
            raw={},
        )

    def _load_array(self, inp: EngineInput):
        if inp.audio is not None:
            return inp.audio
        import librosa
        audio, _ = librosa.load(inp.audio_path, sr=16000, mono=True)
        return audio

    def unload(self) -> None:
        if self._model is not None:
            del self._model
            self._model = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        gc.collect()
        logger.info("Typhoon RT unloaded, VRAM freed")


def _word_entries(hyp) -> list[dict]:
    """Pull a [{'word'|'text', 'start', 'end'}, ...] list from a NeMo hypothesis,
    whatever shape this NeMo version uses. Returns [] if none are exposed."""
    ts = getattr(hyp, "timestamp", None)
    if isinstance(hyp, dict):
        ts = hyp.get("timestamp", ts)
    if isinstance(ts, dict):
        for key in ("word", "words", "segment"):
            if ts.get(key):
                return ts[key]
    return []


def _hyp_text(hyp) -> str:
    if isinstance(hyp, str):
        return hyp
    if isinstance(hyp, dict):
        return hyp.get("text", "")
    return getattr(hyp, "text", "") or ""


def _hyp_to_tokens(hyp, audio_ms: int) -> list[RecognizedToken]:
    """Map a NeMo hypothesis to RecognizedTokens (verbatim text, confidence=None).

    Prefers real per-word timestamps; falls back to distributing the words evenly
    across the clip when the model exposes none."""
    entries = _word_entries(hyp)
    tokens: list[RecognizedToken] = []
    if entries:
        for e in entries:
            text = (e.get("word") or e.get("text") or "").strip()
            if not text:
                continue
            start_ms = int(float(e.get("start", 0.0)) * 1000)
            end_ms = int(float(e.get("end", e.get("start", 0.0))) * 1000)
            if end_ms <= start_ms:
                end_ms = start_ms + 1
            tokens.append(RecognizedToken(
                text=text, start_ms=start_ms, end_ms=end_ms,
                confidence=None, script=detect_script(text),
            ))
        return tokens

    # No timestamps → even split (still a usable hypothesis for the reconciler).
    words = _hyp_text(hyp).split()
    if not words:
        return []
    step = max(1, audio_ms // len(words))
    for i, w in enumerate(words):
        tokens.append(RecognizedToken(
            text=w, start_ms=i * step, end_ms=(i + 1) * step,
            confidence=None, script=detect_script(w),
        ))
    return tokens
