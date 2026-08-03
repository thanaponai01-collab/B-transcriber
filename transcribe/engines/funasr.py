"""Engine B candidate — FunASR adapter, currently wired to SenseVoiceSmall.

**NOT VIABLE FOR THIS PROJECT (confirmed 2026-07-16): SenseVoiceSmall does not
support Thai.** Its own model card (README.md, `language=` kwarg docstring)
lists exactly five languages: `zh` (Mandarin), `en`, `yue` (Cantonese), `ja`,
`ko` — no `th`. With `language="auto"` (below), its language-ID misclassifies
Thai speech as Cantonese and decodes it as Chinese-script text throughout —
verified by inspecting raw output: `result["text"]` carries an explicit
`<|yue|>` (Cantonese) tag, and every emitted "word" is a CJK Unified
Ideograph codepoint (e.g. U+56F0 '困'), not Thai script at all.

Every harness probe of this engine to date — including the two run against
the 2026-07-16 gold set (`--engine-b funasr` alone showed BER "improved" but
WER_latin regressed; `--engine-b funasr --llm-enabled` was byte-identical to
that, because Engine A/B token text never overlaps enough for align_hyp.align
to ever produce a real disagreement slot — 0 of 52 slots had both candidates
on a sample clip) — was measuring this Cantonese/Chinese misdetection, not a
genuine Thai-code-switch accuracy tradeoff. The apparent "BER improvement"
in the plain probe is not trustworthy evidence of decorrelation value; do not
cite it. See TODO_LEDGER.md for the correction and CLAUDE.md's engine table.

There is no language code in SenseVoiceSmall's `language=` kwarg that fixes
this — Thai genuinely isn't in the model's training languages, so this is a
model-selection dead end for this project, not an adapter bug. The adapter
code below is left intact (its sentence_info/words parsing, hotword
injection, and load/unload discipline are all otherwise correct and could be
reused for a future FunASR checkpoint that does support Thai), but do not
activate `engine_b: funasr` in production and do not re-probe it as a
Thai-code-switch candidate without a different underlying model.
"""

from __future__ import annotations

import logging

import torch

from transcribe.contracts import EngineInput, EngineResult, RecognizedToken, detect_script
from transcribe.engines.base import Engine
from transcribe.engines.registry import register

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "FunAudioLLM/SenseVoiceSmall"


@register("funasr")
class FunASREngine(Engine):
    """Wraps FunASR's SenseVoiceSmall for multilingual + code-switch transcription."""

    def __init__(self, model_id: str = _DEFAULT_MODEL, device: str = "cuda"):
        self._model_id = model_id
        self._device = device
        self._model = None

    def load(self) -> None:
        from funasr import AutoModel

        logger.info("Loading FunASR: %s", self._model_id)
        self._model = AutoModel(
            model=self._model_id,
            hub="hf",  # ModelScope (funasr's default hub) 404s for this model outside China
            trust_remote_code=True,
            vad_model="fsmn-vad",
            vad_kwargs={"max_single_segment_time": 30000},
            device=self._device,
        )
        logger.info("FunASR loaded on %s", self._device)

    def transcribe(self, inp: EngineInput) -> EngineResult:
        assert self._model is not None, "load() must be called first"

        # FunASR needs a path; write one if the caller only supplied a decoded array.
        audio_path = inp.audio_path
        tmp_path = None
        if audio_path is None and inp.audio is not None:
            import tempfile, soundfile as sf
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_path = f.name
            sf.write(tmp_path, inp.audio, 16000)
            audio_path = tmp_path

        try:
            result = self._model.generate(
                input=audio_path,
                cache={},
                language="auto",
                use_itn=True,
                batch_size_s=60,
                output_timestamp=True,
                hotword=" ".join(inp.bias_terms) if inp.bias_terms else None,
            )
        finally:
            if tmp_path is not None:
                import os
                os.unlink(tmp_path)

        tokens: list[RecognizedToken] = []
        raw_list = result if isinstance(result, list) else [result]
        for item in raw_list:
            sentence_info = item.get("sentence_info", [])
            words = item.get("words", [])
            word_timestamps = item.get("timestamp", [])
            if sentence_info:
                # Some FunASR models (e.g. Paraformer) return sentence-level spans.
                for seg in sentence_info:
                    text = seg.get("text", "").strip()
                    if not text:
                        continue
                    start_ms = int(seg.get("start", 0))
                    end_ms = int(seg.get("end", start_ms + 500))
                    tokens.append(RecognizedToken(
                        text=text,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        confidence=seg.get("confidence"),
                        script=detect_script(text),
                    ))
            elif words and word_timestamps and len(words) == len(word_timestamps):
                # SenseVoiceSmall: no sentence_info, but per-word text + [start, end]
                # ms pairs of equal length. Special tokens like <|yue|>/<|withitn|>
                # live in `text`, not in `words`, so no stripping needed here.
                for word, (start_ms, end_ms) in zip(words, word_timestamps):
                    word = word.strip()
                    if not word:
                        continue
                    tokens.append(RecognizedToken(
                        text=word,
                        start_ms=int(start_ms),
                        end_ms=int(end_ms),
                        confidence=None,
                        script=detect_script(word),
                    ))
            else:
                # Last-resort fallback: treat whole result as one token spanning
                # the full input (VAD already bounded it to speech, so use the
                # last word-timestamp end if any, else the caller's audio length).
                text = item.get("text", "").strip()
                if text:
                    end_ms = int(word_timestamps[-1][1]) if word_timestamps else 5000
                    tokens.append(RecognizedToken(
                        text=text, start_ms=0, end_ms=end_ms,
                        confidence=None, script=detect_script(text),
                    ))

        return EngineResult(tokens=tokens, engine_name="funasr", raw={"result": raw_list})

    def unload(self) -> None:
        if self._model is not None:
            del self._model
            self._model = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("FunASR unloaded, VRAM freed")
