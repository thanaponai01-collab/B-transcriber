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
import os
import sys
from pathlib import Path

from transcribe.contracts import EngineInput, EngineResult, RecognizedToken, detect_script
from transcribe.engines.base import Engine
from transcribe.engines.registry import register
from transcribe.flywheel.inject import BiasTerm, build_prompt

logger = logging.getLogger(__name__)


def _register_cuda_dll_dirs() -> None:
    """Make the pip nvidia-*-cu12 wheels' bundled DLLs (cublas64_12.dll,
    cudnn64_9.dll, ...) loadable by CTranslate2 on Windows.

    Those wheels drop their DLLs under site-packages/nvidia/<pkg>/bin, which is
    never on PATH. torch works around the equivalent problem for its own
    (bundled, different-version) CUDA libs by registering torch/lib itself, but
    that's a separate cublas64_13.dll — CTranslate2 needs the CUDA-12 one.
    CTranslate2 resolves it via a bare LoadLibrary call deep inside its native
    code (lazily, on first GPU op) rather than through Python's import
    machinery, so os.add_dll_directory() does not cover it (that only affects
    extension-module imports and ctypes loads) — PATH is the search list a bare
    LoadLibrary call actually consults, so that's what has to be extended.
    Without this, load fails with 'cublas64_12.dll is not found or cannot be
    loaded' even though the DLL is present in the venv.
    """
    if sys.platform != "win32":
        return
    nvidia_root = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    if not nvidia_root.is_dir():
        return
    bin_dirs = [str(p) for p in nvidia_root.glob("*/bin")]
    path = os.environ.get("PATH", "")
    for bin_dir in bin_dirs:
        if bin_dir not in path:
            path = bin_dir + os.pathsep + path
    os.environ["PATH"] = path


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

# Truncated-tail recovery: faster-whisper occasionally stops generating well
# before a window's audio actually ends (early EOS on a hard passage), then
# stretches the *last* word's end-timestamp out to the window boundary to
# fill the gap — so several real seconds of dropped speech show up as one
# absurdly long "word" instead of an obvious hole. _TRUNCATION_TAIL_MS is how
# long a single word's span has to be to count as suspicious;
# _TRUNCATION_STRETCH_TOL_MS is how close its end has to land to the window's
# own end to count as "stretched to fill". _TRUNCATION_LOOKBACK_MS bounds how
# far back _find_safe_cut searches for a genuine inter-token pause to cut on.
# See _recover_truncated_tail.
_TRUNCATION_TAIL_MS = 1500
_TRUNCATION_STRETCH_TOL_MS = 500
_TRUNCATION_LOOKBACK_MS = 2500


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


def _sentence_boundary_offsets(text: str) -> list[int]:
    """Character offsets in `text` where pythainlp's crfcut model believes a new
    sentence begins (offset 0 excluded — the first token always starts a cue
    regardless). crfcut is a CRF trained to segment *unpunctuated* running
    text, which is what Whisper's raw Thai output is (no periods/commas) —
    this is the intended use case, not a punctuation-based fallback.
    Best-effort: any failure (missing optional dependency, model fetch
    issue) degrades to no forced sentence breaks rather than raising, since
    the gap/length heuristics below still produce usable cues on their own.
    """
    try:
        from pythainlp.tokenize import sent_tokenize
        sentences = sent_tokenize(text, engine="crfcut", keep_whitespace=True)
    except Exception:
        logger.warning("Sentence tokenization unavailable — cues will not be "
                        "forced to start on sentence boundaries", exc_info=True)
        return []
    offsets = []
    pos = 0
    for sent in sentences:
        if pos:
            offsets.append(pos)
        pos += len(sent)
    return offsets


def _group_words_into_cues(words, gap_ms=_CUE_GAP_MS, target_ms=_CUE_TARGET_MS,
                           target_chars=_CUE_TARGET_CHARS):
    """Group Whisper word-pieces into subtitle-length phrase cues at real word boundaries.

    `words` is a list of (text, start_ms, end_ms, confidence) — confidence is the
    source word-piece's probability, or None if the engine didn't report one.
    Whisper word-pieces for spaceless Thai are sub-word and only sporadically
    carry a leading space, so they cannot be used to find word boundaries — a
    long spaceless run would never break. Instead we rebuild the full text with
    a per-character timeline, segment it with pythainlp (Latin/whitespace
    preserved), and group whole words into cues.

    A cue must never start mid-sentence: a long sentence can still be split into
    several cues (on a silence gap >= gap_ms, or once target_ms / target_chars is
    hit, same as before), but a cue break is also forced at every sentence
    boundary crfcut finds, so a cue never opens with the tail of one sentence
    fused to the head of the next. Sentence detection on raw ASR output (no
    punctuation, colloquial speech) is inherently imperfect — treat it as a
    heuristic that reduces mid-sentence cue starts, not a guarantee.
    Returns list of (text, start_ms, end_ms, confidence) — confidence is the mean
    of the constituent word-pieces' probabilities, or None if none carried one.
    """
    from pythainlp.tokenize import word_tokenize

    # 1. per-character timeline (each char inherits its source piece's span + confidence)
    chartime: list[tuple[int, int]] = []
    charconf: list[float | None] = []
    chars: list[str] = []
    for txt, s, e, conf in words:
        for ch in txt:
            chars.append(ch)
            chartime.append((s, e))
            charconf.append(conf)
    if not chars:
        return []
    full_text = "".join(chars)

    # 2. real word boundaries (pythainlp keeps Latin runs and spaces intact)
    toks = word_tokenize(full_text, keep_whitespace=True)

    # 2b. sentence-start offsets in the same char coordinates as `toks` below.
    boundary_offsets = _sentence_boundary_offsets(full_text)
    boundary_idx = 0

    # 3. map each token back to its time span + confidence + char start via the char timeline
    timed: list[tuple[str, int, int, float | None, int]] = []
    pos = 0
    for t in toks:
        start = chartime[pos][0]
        end = chartime[pos + len(t) - 1][1]
        confs = [c for c in charconf[pos:pos + len(t)] if c is not None]
        conf = sum(confs) / len(confs) if confs else None
        timed.append((t, start, end, conf, pos))
        pos += len(t)

    # 4. greedy group whole words into cues. Whitespace tokens are buffered and only
    # kept once a real word follows in the same cue, so a cue never starts or ends on
    # whitespace (a trailing space carries the next word's timing and would corrupt
    # the cue's end time and the gap check).
    cues: list[tuple[str, int, int, float | None]] = []
    cur: list[tuple[str, int, int, float | None]] = []
    pending_ws: list[tuple[str, int, int, float | None]] = []

    def _close():
        text = "".join(x[0] for x in cur).strip()
        if text:
            confs = [x[3] for x in cur if x[3] is not None]
            conf = sum(confs) / len(confs) if confs else None
            cues.append((text, cur[0][1], cur[-1][2], conf))

    for t, s, e, conf, char_pos in timed:
        if not t.strip():
            if cur:
                pending_ws.append((t, s, e, conf))
            continue
        # Consume any sentence boundary at or before this token — forces a
        # break here even if the gap/length heuristics wouldn't have broken
        # on their own (e.g. no pause between "...ทั้งนั้น" and "อย่า...").
        new_sentence = False
        while boundary_idx < len(boundary_offsets) and char_pos >= boundary_offsets[boundary_idx]:
            new_sentence = True
            boundary_idx += 1
        if cur:
            gap = s - cur[-1][2]
            span = e - cur[0][1]
            n_chars = len("".join(x[0] for x in cur).strip())
            if new_sentence or gap >= gap_ms or span > target_ms or n_chars >= target_chars:
                _close()
                cur = []
        if cur:
            cur.extend(pending_ws)  # interior whitespace only
        pending_ws = []
        cur.append((t, s, e, conf))
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
        _register_cuda_dll_dirs()
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
                        confidence=w.probability, script=detect_script(w.word),
                    ))
        return out

    @staticmethod
    def _find_safe_cut(tokens_before, anchor_ms, lookback_ms=_TRUNCATION_LOOKBACK_MS):
        """Index of the token after which to cut, chosen as the largest
        inter-token gap within lookback_ms of anchor_ms — an actual acoustic
        pause Whisper's own timings already show, not an arbitrary time
        offset. A fixed offset back from the suspicious word can land
        mid-syllable regardless of how big it is (Thai subword pieces don't
        align to word boundaries), which is what caused earlier attempts at
        this fix to reproduce a stray syllable on both sides of the cut.
        Returns None if there aren't at least two tokens within range to
        compare (nothing to cut between)."""
        in_range = [i for i, t in enumerate(tokens_before) if anchor_ms - t.end_ms <= lookback_ms]
        if len(in_range) < 2:
            return None
        best_i, best_gap = None, -1
        for i in range(in_range[0], len(tokens_before) - 1):
            gap = tokens_before[i + 1].start_ms - tokens_before[i].end_ms
            if gap > best_gap:
                best_i, best_gap = i, gap
        return best_i

    def _recover_truncated_tail(self, tokens, sub_audio, common, bs, win_dur_ms):
        """Detect and recover content dropped by an early-EOS decode within one
        long-span window (see _TRUNCATION_TAIL_MS above for the failure mode).
        One-shot: redecodes standalone from the nearest safe cut point (see
        _find_safe_cut) to the window's end (a much shorter, easier decode)
        and concatenates — no overlap-and-dedup splice, since Thai's lack of
        clean word boundaries makes stitch.py's exact-text dedup miss the
        resulting near-duplicates (verified empirically while building this:
        a fixed-offset cut reproduced a stray syllable on both sides no
        matter how the offset was tuned). No recursion — if the redecode
        hits the same issue, its result is kept as-is."""
        if not tokens:
            return tokens, bs
        last = tokens[-1]
        dur = last.end_ms - last.start_ms
        if dur < _TRUNCATION_TAIL_MS or win_dur_ms - last.end_ms > _TRUNCATION_STRETCH_TOL_MS:
            return tokens, bs

        cut_i = self._find_safe_cut(tokens[:-1], last.start_ms)
        if cut_i is None:
            return tokens, bs
        kept = tokens[:cut_i + 1]
        tail_start_ms = tokens[cut_i + 1].start_ms
        tail_audio = sub_audio[int(tail_start_ms / 1000 * _SR):]
        if len(tail_audio) < _SR * 0.5:
            return tokens, bs

        segments, bs = self._decode(tail_audio, None, False, common, bs)
        tail_tokens = self._words_of(segments)
        if not tail_tokens:
            return tokens, bs
        for t in tail_tokens:
            t.start_ms += tail_start_ms
            t.end_ms += tail_start_ms

        merged = kept + tail_tokens
        logger.info("Recovered truncated tail: suspect word spanned %d-%dms, "
                    "redecoded from %.2fs -> %d token(s)",
                    last.start_ms, last.end_ms, tail_start_ms / 1000, len(tail_tokens))
        return merged, bs

    def _transcribe_batched(self, audio, language_hint, initial_prompt) -> list[tuple[str, int, int, float | None]]:
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
        words: list[tuple[str, int, int, float | None]] = []

        spans = _vad_speech_spans(audio, self._vad_threshold, self._vad_min_silence_ms)
        normal = [(s, e) for s, e in spans if e - s <= _LONG_SPAN_SAFE_S]
        long_spans = [(s, e) for s, e in spans if e - s > _LONG_SPAN_SAFE_S]

        if normal:
            # One batched call for every normal-length span (own VAD spans, already
            # each under the encoder cap, so no arbitrary internal re-split happens).
            clip = [{"start": s, "end": e} for s, e in normal]
            segments, bs = self._decode(audio, clip, False, common, bs)
            for tok in self._words_of(segments):
                words.append((tok.text, tok.start_ms, tok.end_ms, tok.confidence))
        elif not long_spans:
            # No speech spans detected at all (rare) — fall back to faster-whisper's
            # own automatic VAD/whole-file path rather than emitting nothing.
            segments, bs = self._decode(audio, None, True, common, bs)
            for tok in self._words_of(segments):
                words.append((tok.text, tok.start_ms, tok.end_ms, tok.confidence))

        for span_start, span_end in long_spans:
            chunk_tokens = []
            for win_start, win_end in _split_long_span(span_start, span_end):
                sub_audio = audio[int(win_start * _SR):int(win_end * _SR)]
                segments, bs = self._decode(sub_audio, None, False, common, bs)
                win_tokens = self._words_of(segments)
                win_dur_ms = int(round((win_end - win_start) * 1000))
                win_tokens, bs = self._recover_truncated_tail(win_tokens, sub_audio, common, bs, win_dur_ms)
                for t in win_tokens:  # offset local → global
                    t.start_ms += int(win_start * 1000)
                    t.end_ms += int(win_start * 1000)
                chunk_tokens.append(stitch.ChunkTokens(
                    win_tokens, int(win_start * 1000), int(win_end * 1000)))
            logger.info("Long pause-free span %.1fs-%.1fs decoded as %d overlapping window(s)",
                        span_start, span_end, len(chunk_tokens))
            for tok in stitch.stitch(chunk_tokens):
                words.append((tok.text, tok.start_ms, tok.end_ms, tok.confidence))

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
                confidence=conf, script=detect_script(text),
            )
            for text, start, end, conf in _group_words_into_cues(
                words, gap_ms=self._cue_gap_ms, target_ms=self._cue_max_ms)
        ]

        return EngineResult(
            tokens=tokens,
            engine_name="faster_whisper",
            timestamps_final=True,  # phrase cues are final; skip re-align
            # 5.4: keep the raw per-word list. Tokens persisted to the DB are phrase
            # cues; word granularity is re-derived on demand from here (CutDeck Phase
            # 5 filler excision needs word-level cuts inside a cue).
            raw={"words": [{"text": t, "start_ms": s, "end_ms": e, "confidence": c} for t, s, e, c in words]},
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
