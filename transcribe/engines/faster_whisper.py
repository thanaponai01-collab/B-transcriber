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

from transcribe.audio import Window, WindowPolicy, speech_windows
from transcribe.contracts import EngineInput, EngineResult, RecognizedToken, detect_script
from transcribe.cues import (
    CUE_GAP_MS,
    CUE_SPACE_MIN_CHARS,
    CUE_SPACE_MIN_MS,
    CUE_SPLIT_ALGORITHM,
    CUE_TARGET_CHARS,
    CUE_TARGET_MS,
    CuePolicy,
    split_cues,
)
from transcribe.engines.base import Engine
from transcribe.engines.registry import register
from transcribe.flywheel.inject import BiasTerm, build_prompt

logger = logging.getLogger(__name__)


def _register_cuda_dll_dirs() -> str:
    """Make the pip nvidia-*-cu12 wheels' bundled DLLs (cublas64_12.dll,
    cudnn64_9.dll, ...) loadable by CTranslate2 on Windows. Returns the PATH
    value from before mutation, so the caller can restore it later.

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

    CALLER MUST RESTORE PATH ON unload(): this prepends a CUDA-12 cuDNN
    (cudnn64_9.dll) ahead of everything else on PATH, process-wide. A
    same-process engine loaded afterward that resolves its OWN cuDNN via
    Windows' DLL search order — e.g. NeMo/PyTorch (torch 2.13+cu130, a
    different CUDA generation) — can have Windows hand it THIS prepended
    cudnn64_9.dll instead of the one it actually linked against, producing
    'CUDNN_STATUS_SUBLIBRARY_VERSION_MISMATCH' on its very first conv forward
    pass. Reproduced 2026-07-16: typhoon_rt (NeMo) works standalone but
    crashes the same way after only calling this function — no CTranslate2
    model even needs to load — confirming the PATH mutation itself, not GPU
    residency, is the cause. This makes the mutation load()-scoped instead of
    process-lifetime: see FasterWhisperEngine.unload().
    """
    if sys.platform != "win32":
        return os.environ.get("PATH", "")
    original_path = os.environ.get("PATH", "")
    nvidia_root = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    if not nvidia_root.is_dir():
        return original_path
    bin_dirs = [str(p) for p in nvidia_root.glob("*/bin")]
    path = original_path
    for bin_dir in bin_dirs:
        if bin_dir not in path:
            path = bin_dir + os.pathsep + path
    os.environ["PATH"] = path
    return original_path


# Converted once via ct2-transformers-converter (see README). Repo-root-relative so
# it resolves regardless of the caller's cwd.
_DEFAULT_MODEL = str(Path(__file__).resolve().parents[2] / "models" / "whisper-th-medium-ct2")

# Cue segmentation lives in transcribe/cues/ — this adapter only builds a
# CuePolicy from its constructor kwargs and hands the word pieces over. The
# knob defaults are imported above so the engine's signature keeps naming the
# same values it always did.

_SR = 16000

# Whisper's encoder hard-caps a single decode window at ~30s. A speech run longer
# than this with no pause anywhere near the cap forces faster-whisper's own VAD to
# split "aggressively" mid-utterance with no overlap — decode quality collapses
# right at that seam (observed: several seconds of garbled/missing text at the
# cut). Any span longer than _LONG_SPAN_SAFE_S gets split into our own overlapping
# windows instead (transcribe/audio/windows.py), decoded separately, and stitched
# back together — the same seam-recovery trick chunk engines get from
# config.yaml's chunk_overlap_ms, applied here to this whole-file engine's rare
# long-pause-free-run case.
# Tuning note: shrinking _LONG_SPAN_SAFE_S (e.g. to 15-20s) recovers a decode-
# quality drop that can still happen *within* a single 25s window on very dense
# speech, but widening the overlap that comes with it exposes stitch.py's dedup
# to more words in the ambiguous zone — Thai has no word boundaries, so two
# independent decodes of the same audio often tokenize it slightly differently,
# producing visible stutter (e.g. "ที่ี่เกี่ี่ยว") across many seams. Verified
# empirically: 25s/4s stutter-free with one small residual gap on a hard passage;
# 15-20s recovers that gap but stutters broadly.
#
# Update (2026-07-30): that stutter turned out NOT to be a text-matching problem
# — the seam duplicates matched on text fine and were lost to stitch.py's IoU
# gate, which is structurally 0.0 for the zero-length combining-mark pieces
# Whisper emits for Thai. stitch.py now also accepts centre-coincident
# duplicates (_coincident), which fixed the observed stutter at 25s. Re-probing
# a shorter _LONG_SPAN_SAFE_S is now worth doing, but measure it — the residual
# artifacts here are the model stuttering inside one window, which no amount of
# seam handling can fix.
_LONG_SPAN_SAFE_S = 25.0
_LONG_SPAN_OVERLAP_S = 4.0

# Truncated-tail recovery: faster-whisper occasionally stops generating well
# before a window's audio actually ends (early EOS on a hard passage), then
# stretches the *last* word's end-timestamp out toward the window boundary to
# fill the gap — so several real seconds of dropped speech show up as one
# absurdly long "word" instead of an obvious hole. _TRUNCATION_TAIL_MS is how
# long a single word's span has to be to count as suspicious.
# _TRUNCATION_LOOKBACK_MS bounds how far back _find_safe_cut searches for a
# genuine inter-token pause to cut on. See _recover_truncated_tail.
#
# Update (2026-08-10, TODO_LEDGER.md incident investigation): this used to
# also require the suspicious word's end to land within 500ms of the
# window's own end ("stretched all the way to the boundary") before
# attempting recovery. Confirmed on real production audio that this was too
# strict — several genuine content-loss cases had a suspicious word ending
# 1.5-4s *short* of the window boundary (the model produced a stray fragment
# then simply stopped, without reaching for the boundary at all), and were
# silently skipped. Redecoding the same passage as a differently-windowed
# clip recovered real, coherent speech at every one of those spots. The
# recovery attempt is now gated only on the word's own suspicious duration
# plus there being meaningful leftover audio to redecode (checked below via
# the tail-audio length) — not on how close it lands to the window edge.
_TRUNCATION_TAIL_MS = 1500
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


@register("faster_whisper")
class FasterWhisperEngine(Engine):
    """Thai-specialist Whisper via CTranslate2."""

    prefers_whole_file = True

    def __init__(self, model_id: str = _DEFAULT_MODEL, device: str = "cuda",
                 compute_type: str | None = None, beam_size: int = 5,
                 cue_gap_ms: int = CUE_GAP_MS, cue_max_ms: int = CUE_TARGET_MS,
                 cue_target_chars: int = CUE_TARGET_CHARS,
                 cue_space_min_chars: int = CUE_SPACE_MIN_CHARS,
                 cue_space_min_ms: int = CUE_SPACE_MIN_MS,
                 cue_split_algorithm: str = CUE_SPLIT_ALGORITHM,
                 bias_prompt_budget: int = 200, batch_size: int = 8,
                 vad_threshold: float = 0.35, vad_min_silence_ms: int = 500,
                 config: dict | None = None):
        self._model_id = model_id
        self._device = device
        # compute_type override lets an 8GB card fall back to int8_float16 if a
        # large model OOMs at float16. None → pick a sane default per device.
        self._compute_type = compute_type
        self._beam_size = beam_size
        self._bias_prompt_budget = bias_prompt_budget
        self._batch_size = batch_size
        # Cue splitting is transcribe/cues/'s job; this adapter only decides the
        # policy. Assembled once at construction — pure, cheap, no GPU.
        # HANDOFF_THAI_BREAK_ATOMS.md: the break-atom lexicon it carries is
        # consumed by both split algorithms. `config` is the full pipeline config
        # (not the engines.faster_whisper sub-block) so `thai_atoms` and
        # `normalization.exception_lexicon` are both visible.
        from transcribe.thai.atoms import default_lexicon
        self._cue_policy = CuePolicy(
            gap_ms=cue_gap_ms,
            target_ms=cue_max_ms,
            target_chars=cue_target_chars,
            space_min_chars=cue_space_min_chars,
            space_min_ms=cue_space_min_ms,
            algorithm=cue_split_algorithm,
            lexicon=default_lexicon(config),
        )
        # This is a whole-file engine (prefers_whole_file=True), so ingest.py's VAD
        # never runs on this audio — we window it ourselves via the shared
        # transcribe/audio/ seam using these thresholds, instead of letting
        # faster-whisper fall back to its defaults (threshold=0.5,
        # min_silence_duration_ms=2000), which clip soft Thai sentence-final
        # particles (ครับ/ค่ะ) exactly like ingest.vad_threshold's docstring warns
        # about. Defaulting these to match config.yaml's tuned ingest values keeps
        # both VAD paths consistent.
        #
        # ingest.py's VAD is deliberately NOT behind this seam (investigated for
        # issue #4): it runs a different Silero (the `silero-vad` pip package, not
        # faster_whisper's vendored copy) at different settings (threshold 0.5,
        # min_silence 300ms, plus a min_speech floor), then sub-splits on raw RMS
        # energy, and its output is a persisted master timeline of BOTH speech and
        # silence rather than decodable windows. Sharing an implementation would
        # mean changing one of the two engines' detection behaviour — a probe, not
        # a refactor. See transcribe/audio/windows.py's module docstring.
        self._window_policy = WindowPolicy(
            vad_threshold=vad_threshold,
            vad_min_silence_ms=vad_min_silence_ms,
            max_span_s=_LONG_SPAN_SAFE_S,
            overlap_s=_LONG_SPAN_OVERLAP_S,
        )
        self._model = None
        self._pipeline = None
        self._pre_load_path: str | None = None

    def load(self) -> None:
        # Restored in unload() — see _register_cuda_dll_dirs's docstring for
        # why this PATH mutation must not outlive this engine's residency.
        self._pre_load_path = _register_cuda_dll_dirs()
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

    def _recover_truncated_tail(self, tokens, sub_audio, common, bs):
        """Detect and recover content dropped by an early-EOS decode within one
        long-span window. Two independent failure modes, both early-EOS, that
        look nothing alike on the wire:

        (A) faster-whisper stretches the *last* word's own timestamp out to
        (near) the window's end to paper over the gap — see _TRUNCATION_TAIL_MS
        above, and its 2026-08-10 update for why this no longer requires the
        suspicious word to reach the window's own end.

        (B) 2026-08-10 incident (this update): faster-whisper just stops, with
        a totally normal-duration last word, leaving real undecoded audio
        sitting after it — confirmed on production audio (job with a 45.6s
        long-span clip): window 1's last word ended at 17.58s with an ordinary
        180ms duration while its own window ran to 25s, silently dropping ~3.4s
        of real speech that (A)'s stretched-word check can never see, since
        there's no anomalous word to trigger on.

        Both redecode standalone (a much shorter, easier decode) and
        concatenate — no overlap-and-dedup splice, since Thai's lack of clean
        word boundaries makes stitch.py's exact-text dedup miss the resulting
        near-duplicates (verified empirically while building the original (A)
        fix: a fixed-offset cut reproduced a stray syllable on both sides no
        matter how the offset was tuned). No recursion — if the redecode hits
        the same issue, its result is kept as-is."""
        if not tokens:
            return tokens, bs
        last = tokens[-1]
        win_dur_ms = len(sub_audio) / _SR * 1000
        dur = last.end_ms - last.start_ms
        trailing_gap_ms = win_dur_ms - last.end_ms

        if dur >= _TRUNCATION_TAIL_MS:
            # (A) the last word itself is the suspect — discard it too and
            # redecode from a genuine inter-token pause before it.
            cut_i = self._find_safe_cut(tokens[:-1], last.start_ms)
            if cut_i is None:
                return tokens, bs
            kept = tokens[:cut_i + 1]
            tail_start_ms = tokens[cut_i + 1].start_ms
        elif trailing_gap_ms >= _TRUNCATION_TAIL_MS:
            # (B) the last word is trustworthy — keep it, redecode only the
            # real leftover audio after it.
            kept = tokens
            tail_start_ms = last.end_ms
        else:
            return tokens, bs

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
        logger.info("Recovered truncated tail: redecoded from %.2fs -> %d token(s) "
                    "(window ends %.2fs, last kept word ended %.2fs)",
                    tail_start_ms / 1000, len(tail_tokens), win_dur_ms / 1000, last.end_ms / 1000)
        return merged, bs

    def _transcribe_batched(self, audio, language_hint, initial_prompt,
                             temperature=None, beam_size=None) -> list[tuple[str, int, int, float | None]]:
        """Decode the whole file, splitting+stitching any pause-free run too long
        for Whisper's encoder window (see _LONG_SPAN_SAFE_S). word_timestamps +
        the anti-hallucination knobs are all supported by the batched signature
        (verified against fw 1.2.x).

        temperature: None (default) omits the key entirely, so faster-whisper
        falls through to its own cascading fallback list — production
        behaviour, byte-identical to before this param existed. A scalar
        pins decode to that single temperature.

        IMPORTANT (found probing HANDOFF_ONE_ENGINE §6 Phase D, 2026-08-05):
        `temperature` alone is a no-op through this batched path when beam_size
        stays at its production value. faster-whisper's
        BatchedInferencePipeline.generate_segment_batched always calls
        ctranslate2's Whisper.generate(beam_size=options.beam_size, ...) — beam
        search is deterministic search, not sampling, and CTranslate2's
        sampling_temperature has no effect while beam_size>1 (verified against
        installed faster-whisper 1.2.1 source: transcribe.py's
        generate_segment_batched never reads options.best_of and always passes
        the fixed beam_size). A temperature override only produces a genuinely
        different decode when paired with beam_size=1 (switches CTranslate2
        into sampling mode). See TODO_LEDGER.md "HANDOFF_ONE_ENGINE Phase D".

        beam_size: None (default) uses self._beam_size (production, 5). An
        override lets a self-ensemble second hypothesis decode at beam_size=1
        (+ temperature>0) to get real sampling diversity from the same
        residency, without touching the primary hypothesis's beam width.
        """
        from transcribe.pipeline import stitch

        common = dict(
            language=language_hint or "th",
            task="transcribe",
            initial_prompt=initial_prompt,
            beam_size=beam_size if beam_size is not None else self._beam_size,
            word_timestamps=True,
            condition_on_previous_text=False,
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.6,
        )
        if temperature is not None:
            common["temperature"] = temperature
        bs = self._batch_size
        words: list[tuple[str, int, int, float | None]] = []

        # Windows sharing a span_index are overlapping pieces of one continuous
        # speech run; a span short enough to decode whole yields exactly one
        # window. So a one-window run is a normal span, and a multi-window run is
        # a long pause-free span that needs decode-per-window plus a stitch.
        runs: list[list[Window]] = []
        for w in speech_windows(audio, self._window_policy):
            if runs and runs[-1][0].span_index == w.span_index:
                runs[-1].append(w)
            else:
                runs.append([w])
        normal = [run[0] for run in runs if len(run) == 1]
        long_runs = [run for run in runs if len(run) > 1]

        if normal:
            # One batched call for every normal-length span (own VAD spans, already
            # each under the encoder cap, so no arbitrary internal re-split happens).
            clip = [{"start": w.start_s, "end": w.end_s} for w in normal]
            segments, bs = self._decode(audio, clip, False, common, bs)
            for tok in self._words_of(segments):
                words.append((tok.text, tok.start_ms, tok.end_ms, tok.confidence))
        elif not long_runs:
            # No speech spans detected at all (rare) — fall back to faster-whisper's
            # own automatic VAD/whole-file path rather than emitting nothing.
            segments, bs = self._decode(audio, None, True, common, bs)
            for tok in self._words_of(segments):
                words.append((tok.text, tok.start_ms, tok.end_ms, tok.confidence))

        for run in long_runs:
            chunk_tokens = []
            for win in run:
                sub_audio = audio[int(win.start_s * _SR):int(win.end_s * _SR)]
                segments, bs = self._decode(sub_audio, None, False, common, bs)
                win_tokens = self._words_of(segments)
                win_tokens, bs = self._recover_truncated_tail(win_tokens, sub_audio, common, bs)
                for t in win_tokens:  # offset local → global
                    t.start_ms += win.start_ms
                    t.end_ms += win.start_ms
                chunk_tokens.append(stitch.ChunkTokens(win_tokens, win.start_ms, win.end_ms))
            logger.info("Long pause-free span %.1fs-%.1fs decoded as %d overlapping window(s)",
                        run[0].start_s, run[-1].end_s, len(chunk_tokens))
            for tok in stitch.stitch(chunk_tokens,
                                     seam_window_ms=int(self._window_policy.overlap_s * 1000)):
                words.append((tok.text, tok.start_ms, tok.end_ms, tok.confidence))

        words.sort(key=lambda w: w[1])
        return words

    def transcribe(self, inp: EngineInput, temperature: float | list[float] | None = None,
                    beam_size: int | None = None) -> EngineResult:
        """temperature/beam_size: optional decode overrides — None preserves the
        exact production defaults. Not part of the abstract Engine.transcribe(inp)
        contract; existing callers (transcribe_batch, other engines) are
        unaffected since both are keyword-only with no-op defaults. See
        HANDOFF_ONE_ENGINE §6 (Phase D) and _transcribe_batched's docstring
        (temperature alone is a no-op at beam_size>1 — pair it with beam_size=1
        for real sampling diversity): this lets the pipeline call the same
        loaded residency twice at different decode settings for a
        self-ensemble N-best pair, with zero second model load."""
        assert self._model is not None, "load() must be called first"
        audio = self._load_array(inp)

        # bias terms ride in as initial_prompt (CT2's native biasing channel).
        # GAP-5 / 5.1: budget-aware packing, ranked by learned weight (not insertion
        # order), counted with CT2's own tokenizer so Thai token density is honoured.
        initial_prompt = self._build_bias_prompt(inp) if inp.bias_terms else None

        words = self._transcribe_batched(audio, inp.language_hint, initial_prompt,
                                          temperature=temperature, beam_size=beam_size)

        tokens = [
            RecognizedToken(
                text=text, start_ms=start, end_ms=end,
                confidence=conf, script=detect_script(text),
            )
            for text, start, end, conf in split_cues(words, self._cue_policy)
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
        # Undo _register_cuda_dll_dirs's PATH prepend now that this engine no
        # longer needs it — an engine loaded afterward in this process (e.g. a
        # NeMo-based Engine B) must not inherit a CUDA-12 cudnn64_9.dll ahead
        # of its own on PATH. See that function's docstring for the crash this
        # caused before the fix (CUDNN_STATUS_SUBLIBRARY_VERSION_MISMATCH).
        if self._pre_load_path is not None:
            os.environ["PATH"] = self._pre_load_path
            self._pre_load_path = None
        gc.collect()
        logger.info("FasterWhisper unloaded, VRAM freed")
