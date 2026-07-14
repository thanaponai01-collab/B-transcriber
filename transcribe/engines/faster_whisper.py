"""Engine — faster-whisper (CTranslate2) backend.

Same Whisper checkpoint family as whisper_thai, but run through CTranslate2 instead
of HuggingFace transformers: typically 3-4x faster and lower VRAM at equal accuracy,
which is why it's the default Engine A on the 8GB card. Needs a CT2-converted model
dir (produced once by `ct2-transformers-converter`, see README); it cannot load a raw
HF checkpoint.

CTranslate2 exposes the real Whisper anti-hallucination knobs the HF pipeline buried:
condition_on_previous_text=False stops loops propagating across windows, and the
compression/log-prob/no-speech thresholds drop garbage segments outright.
"""

from __future__ import annotations

import gc
import logging
from pathlib import Path

from transcribe.contracts import EngineInput, EngineResult, RecognizedToken, detect_script
from transcribe.engines.base import Engine
from transcribe.engines.registry import register
from transcribe.flywheel.inject import BiasTerm, build_prompt

logger = logging.getLogger(__name__)

# Converted once via ct2-transformers-converter (see README). Repo-root-relative so
# it resolves regardless of the caller's cwd.
_DEFAULT_MODEL = str(Path(__file__).resolve().parents[2] / "models" / "whisper-th-medium-ct2")

# Phrase-cue grouping. ponytail: fixed heuristics — break on a speech gap, or once a
# cue reaches target length/duration. Tune here if cues read too long/short; gap_ms
# matches the pipeline's segment.gap_ms default (700 ms), target_chars/target_ms are
# subtitle-line sizing.
_CUE_GAP_MS = 700
_CUE_TARGET_MS = 4000
_CUE_TARGET_CHARS = 42

_SR = 16000

# Whisper's encoder hard-caps a single decode window at ~30s. A speech run longer
# than this with no pause anywhere near the cap forces faster-whisper's own VAD to
# split "aggressively" mid-utterance with no overlap — decode quality collapses
# right at that seam (observed: several seconds of garbled/missing text at the
# cut). Any span longer than _LONG_SPAN_SAFE_S gets split into our own overlapping
# windows instead (see _split_long_span), decoded separately, and stitched back
# together — the same seam-recovery trick chunk engines get from
# config.yaml's chunk_overlap_ms, applied here to this whole-file engine's rare
# long-pause-free-run case.
# Tuning note: shrinking _LONG_SPAN_SAFE_S (e.g. to 15-20s) recovers a decode-
# quality drop that can still happen *within* a single 25s window on very dense
# speech, but widening the overlap that comes with it exposes stitch.py's
# exact-text dedup to more words in the ambiguous zone — Thai has no word
# boundaries, so two independent decodes of the same audio often tokenize it
# slightly differently, and dedup misses the near-duplicates, producing visible
# stutter (e.g. "ที่ี่เกี่ี่ยว") across many seams. Verified empirically: 25s/4s
# stutter-free with one small residual gap on a hard passage; 15-20s recovers
# that gap but stutters broadly. Don't lower this without also making stitch.py's
# duplicate match fuzzy (e.g. edit-distance) rather than exact-text.
_LONG_SPAN_SAFE_S = 25.0
_LONG_SPAN_OVERLAP_S = 4.0


def _is_cuda_oom(e: Exception) -> bool:
    """True for a CUDA out-of-memory error, however the stack surfaces it."""
    try:
        import torch
        if isinstance(e, torch.cuda.OutOfMemoryError):
            return True
    except Exception:
        pass
    return "out of memory" in str(e).lower()


def _vad_speech_spans(audio, threshold: float, min_silence_ms: int) -> list[tuple[float, float]]:
    """Real speech spans (in seconds) with NO max-duration cap.

    We deliberately don't use faster-whisper's vad_filter=True path for this —
    its internal VadOptions defaults max_speech_duration_s to the encoder's
    chunk_length and splits long runs "aggressively" at that boundary if no
    silence is nearby. Detecting spans uncapped lets the caller decide how to
    split anything too long, with overlap, instead of an arbitrary hard cut.
    """
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    opts = VadOptions(threshold=threshold, min_silence_duration_ms=min_silence_ms)
    ts = get_speech_timestamps(audio, opts)
    return [(t["start"] / _SR, t["end"] / _SR) for t in ts]


def _split_long_span(start_s: float, end_s: float,
                      max_span_s: float = _LONG_SPAN_SAFE_S,
                      overlap_s: float = _LONG_SPAN_OVERLAP_S) -> list[tuple[float, float]]:
    """Chop a speech span longer than max_span_s into overlapping sub-windows,
    each safely under Whisper's ~30s encoder limit. Returns [(start_s, end_s)]
    unchanged if the span is already short enough."""
    if end_s - start_s <= max_span_s:
        return [(start_s, end_s)]
    stride = max_span_s - overlap_s
    windows = []
    pos = start_s
    while True:
        win_end = min(pos + max_span_s, end_s)
        windows.append((pos, win_end))
        if win_end >= end_s:
            break
        pos += stride
    return windows


def _group_words_into_cues(words, gap_ms=_CUE_GAP_MS, target_ms=_CUE_TARGET_MS,
                           target_chars=_CUE_TARGET_CHARS):
    """Group Whisper word-pieces into subtitle-length phrase cues at real word boundaries.

    `words` is a list of (text, start_ms, end_ms). Whisper word-pieces for spaceless
    Thai are sub-word and only sporadically carry a leading space, so they cannot be
    used to find word boundaries — a long spaceless run would never break. Instead we
    rebuild the full text with a per-character timeline, segment it with pythainlp
    (Latin/whitespace preserved), and group whole words into cues. A new cue starts on
    a silence gap >= gap_ms or once the cue reaches target_ms / target_chars.
    Returns list of (text, start_ms, end_ms).
    """
    from pythainlp.tokenize import word_tokenize

    # 1. per-character timeline (each char inherits its source piece's span)
    chartime: list[tuple[int, int]] = []
    chars: list[str] = []
    for txt, s, e in words:
        for ch in txt:
            chars.append(ch)
            chartime.append((s, e))
    if not chars:
        return []

    # 2. real word boundaries (pythainlp keeps Latin runs and spaces intact)
    toks = word_tokenize("".join(chars), keep_whitespace=True)

    # 3. map each token back to its time span via the char timeline
    timed: list[tuple[str, int, int]] = []
    pos = 0
    for t in toks:
        start = chartime[pos][0]
        end = chartime[pos + len(t) - 1][1]
        pos += len(t)
        timed.append((t, start, end))

    # 4. greedy group whole words into cues. Whitespace tokens are buffered and only
    # kept once a real word follows in the same cue, so a cue never starts or ends on
    # whitespace (a trailing space carries the next word's timing and would corrupt
    # the cue's end time and the gap check).
    cues: list[tuple[str, int, int]] = []
    cur: list[tuple[str, int, int]] = []
    pending_ws: list[tuple[str, int, int]] = []

    def _close():
        text = "".join(x[0] for x in cur).strip()
        if text:
            cues.append((text, cur[0][1], cur[-1][2]))

    for t, s, e in timed:
        if not t.strip():
            if cur:
                pending_ws.append((t, s, e))
            continue
        if cur:
            gap = s - cur[-1][2]
            span = e - cur[0][1]
            n_chars = len("".join(x[0] for x in cur).strip())
            if gap >= gap_ms or span > target_ms or n_chars >= target_chars:
                _close()
                cur = []
        if cur:
            cur.extend(pending_ws)  # interior whitespace only
        pending_ws = []
        cur.append((t, s, e))
    if cur:
        _close()
    return cues


@register("faster_whisper")
class FasterWhisperEngine(Engine):
    """Thai-specialist Whisper via CTranslate2."""

    prefers_whole_file = True

    def __init__(self, model_id: str = _DEFAULT_MODEL, device: str = "cuda",
                 compute_type: str | None = None, beam_size: int = 5,
                 cue_gap_ms: int = _CUE_GAP_MS, cue_max_ms: int = _CUE_TARGET_MS,
                 bias_prompt_budget: int = 200, batch_size: int = 8,
                 vad_threshold: float = 0.35, vad_min_silence_ms: int = 500):
        self._model_id = model_id
        self._device = device
        # compute_type override lets an 8GB card fall back to int8_float16 if a
        # large model OOMs at float16. None → pick a sane default per device.
        self._compute_type = compute_type
        self._beam_size = beam_size
        self._cue_gap_ms = cue_gap_ms
        self._cue_max_ms = cue_max_ms
        self._bias_prompt_budget = bias_prompt_budget
        self._batch_size = batch_size
        # This is a whole-file engine (prefers_whole_file=True), so ingest.py's VAD
        # never runs on this audio — we run our own Silero VAD pass in
        # _transcribe_batched (via _vad_speech_spans) using these thresholds, instead
        # of letting faster-whisper fall back to its defaults (threshold=0.5,
        # min_silence_duration_ms=2000), which clip soft Thai sentence-final
        # particles (ครับ/ค่ะ) exactly like ingest.vad_threshold's docstring warns
        # about. Defaulting these to match config.yaml's tuned ingest values keeps
        # both VAD paths consistent.
        self._vad_threshold = vad_threshold
        self._vad_min_silence_ms = vad_min_silence_ms
        self._model = None
        self._pipeline = None

    def load(self) -> None:
        from faster_whisper import WhisperModel, BatchedInferencePipeline

        compute_type = self._compute_type or ("float16" if self._device != "cpu" else "int8")
        logger.info("Loading FasterWhisper: %s (%s)", self._model_id, compute_type)
        self._model = WhisperModel(self._model_id, device=self._device, compute_type=compute_type)
        # BatchedInferencePipeline VAD-segments the track and decodes voiced regions
        # as parallel batches (WhisperX-style) — ~3× the sequential 30 s-window path
        # on the 3070 (3.1). self._model is kept for tokenizer access + unload.
        self._pipeline = BatchedInferencePipeline(model=self._model)
        logger.info("FasterWhisper (batched) loaded on %s", self._device)

    def _ct2_token_counter(self):
        """CT2's own tokenizer counts prompt tokens (Thai is token-dense; a Latin
        heuristic under-counts). Falls back to inject._approx_tokens if the
        installed faster-whisper doesn't expose hf_tokenizer."""
        tok = getattr(self._model, "hf_tokenizer", None)
        if tok is None:
            return None
        try:
            return lambda s: len(tok.encode(s).ids)
        except Exception:
            return None

    def _build_bias_prompt(self, inp: EngineInput) -> str:
        weights = inp.bias_weights or {}
        terms = [BiasTerm(t, weight=float(weights.get(t, 1.0))) for t in inp.bias_terms]
        return build_prompt(
            terms,
            budget_tokens=self._bias_prompt_budget,
            count_tokens=self._ct2_token_counter(),  # None → inject's approx fallback
        )

    def _load_array(self, inp: EngineInput):
        if inp.audio is not None:
            return inp.audio
        import librosa
        audio, _ = librosa.load(inp.audio_path, sr=16000, mono=True)
        return audio

    def _decode(self, audio_arr, clip_timestamps, vad_filter, common_kwargs, bs):
        """One BatchedInferencePipeline.transcribe call, halving batch_size on CUDA
        OOM. The batched API is a generator that runs inference lazily, so we
        materialize it inside the try — that's where an OOM actually surfaces.
        Mirrors _batch.py's OOM-halving philosophy without reusing it (that path
        is HF-pipeline-specific). Returns (segments, batch_size_used) so the
        caller's next call starts from whatever size succeeded."""
        import torch

        while True:
            try:
                segments, _info = self._pipeline.transcribe(
                    audio_arr,
                    vad_filter=vad_filter,
                    clip_timestamps=clip_timestamps,
                    batch_size=bs,
                    **common_kwargs,
                )
                return list(segments), bs  # materialize here so OOM lands in this try
            except Exception as e:  # noqa: BLE001 — narrowed by _is_cuda_oom
                if _is_cuda_oom(e) and bs > 1:
                    bs = max(1, bs // 2)
                    logger.warning("CUDA OOM in batched decode — retrying at batch_size=%d", bs)
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    continue
                raise

    @staticmethod
    def _words_of(segments) -> list[RecognizedToken]:
        out = []
        for seg in segments:
            for w in (seg.words or []):
                if w.word.strip():  # keep w.word verbatim (its leading space marks the word boundary)
                    out.append(RecognizedToken(
                        text=w.word, start_ms=int(w.start * 1000), end_ms=int(w.end * 1000),
                        confidence=None, script=detect_script(w.word),
                    ))
        return out

    def _transcribe_batched(self, audio, language_hint, initial_prompt) -> list[tuple[str, int, int]]:
        """Decode the whole file, splitting+stitching any pause-free run too long
        for Whisper's encoder window (see _LONG_SPAN_SAFE_S). word_timestamps +
        the anti-hallucination knobs are all supported by the batched signature
        (verified against fw 1.2.x)."""
        from transcribe.pipeline import stitch

        common = dict(
            language=language_hint or "th",
            task="transcribe",
            initial_prompt=initial_prompt,
            beam_size=self._beam_size,
            word_timestamps=True,
            condition_on_previous_text=False,
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.6,
        )
        bs = self._batch_size
        words: list[tuple[str, int, int]] = []

        spans = _vad_speech_spans(audio, self._vad_threshold, self._vad_min_silence_ms)
        normal = [(s, e) for s, e in spans if e - s <= _LONG_SPAN_SAFE_S]
        long_spans = [(s, e) for s, e in spans if e - s > _LONG_SPAN_SAFE_S]

        if normal:
            # One batched call for every normal-length span (own VAD spans, already
            # each under the encoder cap, so no arbitrary internal re-split happens).
            clip = [{"start": s, "end": e} for s, e in normal]
            segments, bs = self._decode(audio, clip, False, common, bs)
            for tok in self._words_of(segments):
                words.append((tok.text, tok.start_ms, tok.end_ms))
        elif not long_spans:
            # No speech spans detected at all (rare) — fall back to faster-whisper's
            # own automatic VAD/whole-file path rather than emitting nothing.
            segments, bs = self._decode(audio, None, True, common, bs)
            for tok in self._words_of(segments):
                words.append((tok.text, tok.start_ms, tok.end_ms))

        for span_start, span_end in long_spans:
            chunk_tokens = []
            for win_start, win_end in _split_long_span(span_start, span_end):
                sub_audio = audio[int(win_start * _SR):int(win_end * _SR)]
                segments, bs = self._decode(sub_audio, None, False, common, bs)
                win_tokens = self._words_of(segments)
                for t in win_tokens:  # offset local → global
                    t.start_ms += int(win_start * 1000)
                    t.end_ms += int(win_start * 1000)
                chunk_tokens.append(stitch.ChunkTokens(
                    win_tokens, int(win_start * 1000), int(win_end * 1000)))
            logger.info("Long pause-free span %.1fs-%.1fs decoded as %d overlapping window(s)",
                        span_start, span_end, len(chunk_tokens))
            for tok in stitch.stitch(chunk_tokens):
                words.append((tok.text, tok.start_ms, tok.end_ms))

        words.sort(key=lambda w: w[1])
        return words

    def transcribe(self, inp: EngineInput) -> EngineResult:
        assert self._model is not None, "load() must be called first"
        audio = self._load_array(inp)

        # bias terms ride in as initial_prompt (CT2's native biasing channel).
        # GAP-5 / 5.1: budget-aware packing, ranked by learned weight (not insertion
        # order), counted with CT2's own tokenizer so Thai token density is honoured.
        initial_prompt = self._build_bias_prompt(inp) if inp.bias_terms else None

        words = self._transcribe_batched(audio, inp.language_hint, initial_prompt)

        tokens = [
            RecognizedToken(
                text=text, start_ms=start, end_ms=end,
                confidence=None, script=detect_script(text),
            )
            for text, start, end in _group_words_into_cues(
                words, gap_ms=self._cue_gap_ms, target_ms=self._cue_max_ms)
        ]

        return EngineResult(
            tokens=tokens,
            engine_name="faster_whisper",
            timestamps_final=True,  # phrase cues are final; skip re-align
            # 5.4: keep the raw per-word list. Tokens persisted to the DB are phrase
            # cues; word granularity is re-derived on demand from here (CutDeck Phase
            # 5 filler excision needs word-level cuts inside a cue).
            raw={"words": [{"text": t, "start_ms": s, "end_ms": e} for t, s, e in words]},
        )

    def unload(self) -> None:
        if self._pipeline is not None:
            del self._pipeline
            self._pipeline = None
        if self._model is not None:
            del self._model
            self._model = None
        gc.collect()
        logger.info("FasterWhisper unloaded, VRAM freed")
