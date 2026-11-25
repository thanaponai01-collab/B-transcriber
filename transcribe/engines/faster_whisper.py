from __future__ import annotations

from bisect import bisect_right
from dataclasses import replace
import logging
import os
import sys
from pathlib import Path

import numpy as np

from transcribe.audio import AudioWindow, Window, WindowPolicy, decode_windows, speech_windows
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


_DEFAULT_MODEL = str(Path(__file__).resolve().parents[2] / "models" / "whisper-th-medium-ct2")

_SR = 16000

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
_TRUNCATION_TAIL_MS = 1500
# When zero-length pieces follow it, a shorter stretch already counts (#94:
# a 1300 ms vowel mark before two 0 ms pieces dropped a clause). Over 4 real
# files + gold audio this flagged only that window and a 6.5 s one.
_TRUNCATION_COLLAPSED_TAIL_MS = 1000
# Trailing pieces this short count as collapsed too, not only 0 ms ones: gold
# Short2 at -1.2 dB ends its first long window on a 6.8 s vowel mark, then a
# 20 ms and a 0 ms piece, and 4 s of speech went undecoded (2026-11-25).
_COLLAPSED_PIECE_MS = 40
_TRUNCATION_LOOKBACK_MS = 2500


def _lib_samples(seconds: float) -> int:
    """faster_whisper's own seconds-to-samples for one clip timestamp: int() of
    that timestamp alone. Code that must agree with the library's sample counts
    goes through here, so a change to its arithmetic is made once."""
    return int(seconds * _SR)


def _lib_seek(seconds: float) -> int:
    """faster_whisper's segment.seek for a clip starting at `seconds`: its sample
    offset, then int() to 10 ms frames."""
    return int(_lib_samples(seconds) / _SR * 100)


def _is_cuda_oom(e: Exception) -> bool:
    try:
        import torch
        if isinstance(e, torch.cuda.OutOfMemoryError):
            return True
    except Exception:
        pass
    return "out of memory" in str(e).lower()


@register("faster_whisper")
class FasterWhisperEngine(Engine):

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
                 config: dict | None = None, recover_short_spans: bool = False,
                 bias_channel: str = "prompt",
                 no_speech_threshold: float = 0.6,
                 log_prob_threshold: float = -1.0,
                 compression_ratio_threshold: float = 2.4):
        self._model_id = model_id
        self._device = device
        self._compute_type = compute_type
        self._beam_size = beam_size
        self._bias_prompt_budget = bias_prompt_budget
        self._batch_size = batch_size
        self._recover_short_spans = recover_short_spans
        self._no_speech_threshold = no_speech_threshold
        self._log_prob_threshold = log_prob_threshold
        self._compression_ratio_threshold = compression_ratio_threshold
        if bias_channel not in ("prompt", "hotwords", "both"):
            raise ValueError(f"bias_channel must be prompt, hotwords or both, got {bias_channel!r}")
        self._bias_channel = bias_channel
        self._hotwords: str | None = None
        self._segment_stats: list[dict] = []
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
        self._pre_load_path = _register_cuda_dll_dirs()
        self._auto_language = None
        from faster_whisper import WhisperModel, BatchedInferencePipeline

        compute_type = self._compute_type or ("float16" if self._device != "cpu" else "int8")
        logger.info("Loading FasterWhisper: %s (%s)", self._model_id, compute_type)
        self._model = WhisperModel(self._model_id, device=self._device, compute_type=compute_type)
        self._pipeline = BatchedInferencePipeline(model=self._model)
        logger.info("FasterWhisper (batched) loaded on %s", self._device)

    def _ct2_token_counter(self):
        tok = getattr(self._model, "hf_tokenizer", None)
        if tok is None:
            return None
        try:
            return lambda s: len(tok.encode(s).ids)
        except Exception:
            return None

    def _note_segments(self, segments, offset_ms: int = 0) -> None:
        for g in segments:
            if getattr(g, "avg_logprob", None) is None:
                continue
            self._segment_stats.append({
                "start_ms": int(g.start * 1000) + offset_ms,
                "end_ms": int(g.end * 1000) + offset_ms,
                "avg_logprob": g.avg_logprob, "no_speech_prob": g.no_speech_prob,
                "compression_ratio": g.compression_ratio})

    @property
    def last_segment_stats(self) -> list[dict]:
        return list(self._segment_stats)

    @staticmethod
    def _build_hotwords(inp: EngineInput, max_terms: int = 30) -> str:
        weights = inp.bias_weights or {}
        ranked = sorted(dict.fromkeys(inp.bias_terms), key=lambda t: -float(weights.get(t, 1.0)))
        return " ".join(ranked[:max_terms])

    def _build_bias_prompt(self, inp: EngineInput) -> str:
        weights = inp.bias_weights or {}
        terms = [BiasTerm(t, weight=float(weights.get(t, 1.0))) for t in inp.bias_terms]
        return build_prompt(
            terms,
            budget_tokens=self._bias_prompt_budget,
            count_tokens=self._ct2_token_counter(),
        )

    def _decode(self, audio_arr, clip_timestamps, vad_filter, common_kwargs, bs):
        import torch

        # BatchedInferencePipeline asserts duration >= duration_after_vad when formatting
        # VAD log info (faster_whisper/transcribe.py:460). For overlapping clips,
        # sum(clip durations) can exceed audio_arr length. Pad audio_arr with zeros so
        # duration >= duration_after_vad without altering any clip content.
        if clip_timestamps and len(audio_arr) > 0:
            # Per-clip conversion mirrors the library's own; one int() of the summed
            # seconds can land a few samples short of it (b6f41d0).
            tot_dur_samples = sum(_lib_samples(c["end"]) - _lib_samples(c["start"]) for c in clip_timestamps)
            if tot_dur_samples > len(audio_arr):
                audio_arr = np.pad(audio_arr, (0, tot_dur_samples - len(audio_arr)), mode="constant")

        while True:
            try:
                if self._pipeline is not None:
                    self._pipeline.last_speech_timestamp = 0.0
                segments, _info = self._pipeline.transcribe(
                    audio_arr,
                    vad_filter=vad_filter,
                    clip_timestamps=clip_timestamps,
                    batch_size=bs,
                    **common_kwargs,
                )
                return list(segments), bs  # materialize here so OOM lands in this try
            except Exception as e:
                if _is_cuda_oom(e) and bs > 1:
                    bs = max(1, bs // 2)
                    logger.warning("CUDA OOM in batched decode — retrying at batch_size=%d", bs)
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    continue
                raise

    @staticmethod
    def _words_of(
        segments,
        no_speech_threshold: float | None = 0.6,
        log_prob_threshold: float | None = -1.0,
    ) -> list[RecognizedToken]:
        out = []
        for seg in segments:
            no_speech = getattr(seg, "no_speech_prob", None)
            avg_logprob = getattr(seg, "avg_logprob", None)
            if (
                no_speech_threshold is not None
                and log_prob_threshold is not None
                and no_speech is not None
                and avg_logprob is not None
                and no_speech > no_speech_threshold
                and avg_logprob < log_prob_threshold
            ):
                continue
            for w in (seg.words or []):
                if w.word.strip():  # keep w.word verbatim (its leading space marks the word boundary)
                    out.append(RecognizedToken(
                        text=w.word, start_ms=int(w.start * 1000), end_ms=int(w.end * 1000),
                        confidence=w.probability, script=detect_script(w.word),
                    ))
        return out

    @staticmethod
    def _find_safe_cut(tokens_before, anchor_ms, lookback_ms=_TRUNCATION_LOOKBACK_MS):
        in_range = [i for i, t in enumerate(tokens_before) if anchor_ms - t.end_ms <= lookback_ms]
        if len(in_range) < 2:
            return None
        best_i, best_gap = None, -1
        for i in range(in_range[0], len(tokens_before) - 1):
            gap = tokens_before[i + 1].start_ms - tokens_before[i].end_ms
            if gap > best_gap:
                best_i, best_gap = i, gap
        return best_i

    @staticmethod
    def _group_segments_by_window(segments, windows: list[Window]) -> list[list]:
        grouped = [[] for _ in windows]
        if not windows or not segments:
            return grouped

        seek_map = {_lib_seek(w.start_s): idx for idx, w in enumerate(windows)}
        all_have_matching_seek = all(
            getattr(s, "seek", None) is not None and getattr(s, "seek", None) in seek_map
            for s in segments
        )
        if all_have_matching_seek:
            for s in segments:
                grouped[seek_map[s.seek]].append(s)
            return grouped

        win_idx = 0
        prev_start = -1.0
        for seg in segments:
            while win_idx < len(windows) - 1 and (
                (prev_start >= 0 and seg.start < prev_start - 0.1)
                or (seg.start > windows[win_idx].end_s + 0.1)
            ):
                win_idx += 1
                prev_start = -1.0
            grouped[win_idx].append(seg)
            prev_start = seg.start
        return grouped

    def _plan_truncated_tail(self, tokens, sub_audio, *, require_speech=False):
        if not tokens and not require_speech:
            return None
        # Collapsed pieces at the end mean Whisper ran out of timeline: the
        # suspect is the last piece longer than that, and less stretch counts (#94).
        body = tokens
        while body and body[-1].end_ms - body[-1].start_ms <= _COLLAPSED_PIECE_MS:
            body = body[:-1]
        stretch_ms = _TRUNCATION_TAIL_MS if body is tokens else _TRUNCATION_COLLAPSED_TAIL_MS
        suspect = body[-1] if body else None
        last = tokens[-1] if tokens else None
        win_dur_ms = len(sub_audio) / _SR * 1000
        dur = suspect.end_ms - suspect.start_ms if suspect else 0
        trailing_gap_ms = win_dur_ms - last.end_ms if last else win_dur_ms
        cut_i = self._find_safe_cut(body[:-1], suspect.start_ms) if dur >= stretch_ms else None

        if last is None:
            kept = []
            tail_start_ms = 0
        elif cut_i is not None:
            kept = body[:cut_i + 1]
            tail_start_ms = body[cut_i + 1].start_ms
        elif body is tokens and dur >= _TRUNCATION_TAIL_MS:
            return None
        elif trailing_gap_ms >= _TRUNCATION_TAIL_MS:
            kept = tokens
            tail_start_ms = last.end_ms
        else:
            return None

        tail_audio = sub_audio[int(tail_start_ms / 1000 * _SR):]
        if len(tail_audio) < _SR * 0.5:
            return None

        clip = None
        if require_speech:
            windows = speech_windows(tail_audio, self._window_policy)
            if not windows:
                return None
            clip = [{"start": w.start_s, "end": w.end_s} for w in windows]
        return tokens, kept, tail_audio, tail_start_ms, clip

    def _batch_recover_tails(self, tail_candidates, common, bs):
        recovered_map = {}
        if not tail_candidates:
            return recovered_map, bs

        tail_common = {k: v for k, v in common.items() if k not in ("initial_prompt", "hotwords")}
        tail_common["initial_prompt"] = None

        if len(tail_candidates) == 1:
            key, (orig_tokens, kept, tail_audio, tail_start_ms, clip) = tail_candidates[0]
            segments, bs = self._decode(tail_audio, clip, False, tail_common, bs)
            tail_tokens = self._words_of(segments, self._no_speech_threshold, self._log_prob_threshold)
            if not tail_tokens:
                recovered_map[key] = orig_tokens
            else:
                for t in tail_tokens:
                    t.start_ms += tail_start_ms
                    t.end_ms += tail_start_ms
                recovered_map[key] = kept + tail_tokens
            return recovered_map, bs

        combined_audio = np.concatenate([plan[2] for _, plan in tail_candidates])
        combined_clips = []
        offset_samples = 0
        tail_ranges = []

        for key, (orig_tokens, kept, tail_audio, tail_start_ms, clip) in tail_candidates:
            offset_s = offset_samples / _SR
            dur_s = len(tail_audio) / _SR
            start_clip_idx = len(combined_clips)
            if clip:
                for c in clip:
                    combined_clips.append({"start": offset_s + c["start"], "end": offset_s + c["end"]})
            else:
                combined_clips.append({"start": offset_s, "end": offset_s + dur_s})
            end_clip_idx = len(combined_clips)
            tail_ranges.append((key, orig_tokens, kept, tail_start_ms, start_clip_idx, end_clip_idx, offset_samples))
            offset_samples += len(tail_audio)

        segments, bs = self._decode(combined_audio, combined_clips, False, tail_common, bs)
        dummy_windows = [
            Window(start_s=c["start"], end_s=c["end"], span_index=idx)
            for idx, c in enumerate(combined_clips)
        ]
        grouped_segs = self._group_segments_by_window(segments, dummy_windows)

        for key, orig_tokens, kept, tail_start_ms, start_idx, end_idx, offset_samp in tail_ranges:
            tail_segs = [seg for sub in grouped_segs[start_idx:end_idx] for seg in sub]
            tail_tokens = self._words_of(tail_segs, self._no_speech_threshold, self._log_prob_threshold)
            if not tail_tokens:
                recovered_map[key] = orig_tokens
            else:
                offset_ms = int(offset_samp / _SR * 1000)
                for t in tail_tokens:
                    t.start_ms = t.start_ms - offset_ms + tail_start_ms
                    t.end_ms = t.end_ms - offset_ms + tail_start_ms
                recovered_map[key] = kept + tail_tokens

        return recovered_map, bs

    def _recover_truncated_tail(self, tokens, sub_audio, common, bs, *, require_speech=False):
        plan = self._plan_truncated_tail(tokens, sub_audio, require_speech=require_speech)
        if plan is None:
            return tokens, bs
        recovered, bs = self._batch_recover_tails([(None, plan)], common, bs)
        merged = recovered[None]
        if merged is tokens:
            return tokens, bs
        tail_start_ms = plan[3]
        tail_tokens = merged[len(plan[1]):]
        win_dur_ms = len(sub_audio) / _SR * 1000
        last = tokens[-1] if tokens else None
        logger.info("Recovered truncated tail: redecoded from %.2fs -> %d token(s) "
                    "(window ends %.2fs, last kept word ended %.2fs)",
                    tail_start_ms / 1000, len(tail_tokens), win_dur_ms / 1000,
                    (last.end_ms / 1000) if last else 0.0)
        return merged, bs

    _AUTO_LANGUAGES = ("th", "en")
    _AUTO_SAMPLE_S = 30

    def _language_score(self, audio, language: str) -> float | None:
        segments, _ = self._model.transcribe(audio, language=language, beam_size=1, vad_filter=True,
                                             condition_on_previous_text=False)
        segments = list(segments)
        tokens = sum(len(seg.tokens) for seg in segments)
        if not tokens:
            return None
        return sum(seg.avg_logprob * len(seg.tokens) for seg in segments) / tokens

    def _resolve_language(self, hint: str | None, audio) -> str | None:
        if hint != "auto":
            return hint
        if len(audio) >= 60 * 16000:
            self._auto_language = None
            return self._pick_language(audio)
        return getattr(self, "_auto_language", None) or "th"

    def _pick_language(self, audio) -> str:
        """`language: auto`: Thai or English for this file. The Thai checkpoint's own language
        detector calls everything Thai (0.97+ on an English broadcast, 2026-11-22), but its
        confidence decoding a sample each way separates them: on 12 samples of 4 files the right
        language scored higher every time. Three 30 s samples (at 20/50/80% of the file), majority
        wins; Thai on a tie or with no speech. Remembered for this loaded engine (gap re-decodes
        reuse it)."""
        if getattr(self, "_auto_language", None):
            return self._auto_language
        n, w = len(audio), self._AUTO_SAMPLE_S * 16000
        votes = {lang: 0 for lang in self._AUTO_LANGUAGES}
        for frac in (0.2, 0.5, 0.8):
            lo = max(0, min(int(n * frac) - w // 2, n - w))
            sample = audio[lo:lo + w]
            scores = {lang: self._language_score(sample, lang) for lang in self._AUTO_LANGUAGES}
            if any(v is None for v in scores.values()):
                continue
            votes[max(scores, key=scores.get)] += 1
        self._auto_language = "en" if votes["en"] > votes["th"] else "th"
        logger.info("language auto: %s (votes %s)", self._auto_language, votes)
        return self._auto_language

    def _transcribe_batched(self, audio, language_hint, initial_prompt,
                             temperature=None, beam_size=None,
                             speech_spans=()) -> list[tuple[str, int, int, float | None]]:
        common = dict(
            language=language_hint or "th",
            task="transcribe",
            initial_prompt=initial_prompt,
            beam_size=beam_size if beam_size is not None else self._beam_size,
            word_timestamps=True,
            condition_on_previous_text=False,
            compression_ratio_threshold=self._compression_ratio_threshold,
            log_prob_threshold=self._log_prob_threshold,
            no_speech_threshold=self._no_speech_threshold,
        )
        if temperature is not None:
            common["temperature"] = temperature
        if self._hotwords:
            common["hotwords"] = self._hotwords
        bs = self._batch_size
        words: list[tuple[str, int, int, float | None]] = []

        runs: list[list[Window]] = []
        if speech_spans:
            raw_windows = speech_windows(audio, self._window_policy, speech_spans=speech_spans)
        else:
            raw_windows = speech_windows(audio, self._window_policy)
        for w in raw_windows:
            if runs and runs[-1][0].span_index == w.span_index:
                runs[-1].append(w)
            else:
                runs.append([w])
        normal = [run[0] for run in runs if len(run) == 1]
        long_runs = [run for run in runs if len(run) > 1]

        if normal:
            clip = [{"start": w.start_s, "end": w.end_s} for w in normal]
            segments, bs = self._decode(audio, clip, False, common, bs)
            self._note_segments(segments)
            decoded = self._words_of(segments, self._no_speech_threshold, self._log_prob_threshold)
            if self._recover_short_spans:
                # Batched clip timestamps are absolute. Group before recovery,
                # convert to span-local times, then restore exactly one offset.
                starts = [w.start_ms for w in normal]
                grouped = [[] for _ in normal]
                outside = []
                for tok in decoded:
                    index = bisect_right(starts, tok.start_ms) - 1
                    if index >= 0 and tok.start_ms <= normal[index].end_ms:
                        grouped[index].append(tok)
                    else:
                        outside.append(tok)
                decoded = outside
                tail_candidates = []
                normal_tokens_map = {}
                for win, span_tokens in zip(normal, grouped):
                    local = [replace(t, start_ms=t.start_ms - win.start_ms,
                                     end_ms=t.end_ms - win.start_ms) for t in span_tokens]
                    span_audio = audio[int(win.start_s * _SR):int(win.end_s * _SR)]
                    plan = self._plan_truncated_tail(local, span_audio, require_speech=True)
                    if plan is not None:
                        tail_candidates.append((win, plan))
                    else:
                        normal_tokens_map[win] = local
                if tail_candidates:
                    recovered_map, bs = self._batch_recover_tails(tail_candidates, common, bs)
                    normal_tokens_map.update(recovered_map)
                for win in normal:
                    local = normal_tokens_map[win]
                    decoded.extend(replace(t, start_ms=t.start_ms + win.start_ms,
                                           end_ms=t.end_ms + win.start_ms) for t in local)
            for tok in decoded:
                words.append((tok.text, tok.start_ms, tok.end_ms, tok.confidence))
        elif not long_runs:
            segments, bs = self._decode(audio, None, True, common, bs)
            self._note_segments(segments)
            for tok in self._words_of(segments, self._no_speech_threshold, self._log_prob_threshold):
                words.append((tok.text, tok.start_ms, tok.end_ms, tok.confidence))

        if long_runs:
            all_long_windows = [win for run in long_runs for win in run]
            long_clip = [{"start": w.start_s, "end": w.end_s} for w in all_long_windows]
            segments, bs = self._decode(audio, long_clip, False, common, bs)
            self._note_segments(segments)
            grouped_segs = self._group_segments_by_window(segments, all_long_windows)

            window_tokens_map = {}
            tail_candidates = []
            for win, w_segs in zip(all_long_windows, grouped_segs):
                toks = self._words_of(w_segs, self._no_speech_threshold, self._log_prob_threshold)
                local = [replace(t, start_ms=t.start_ms - win.start_ms,
                                 end_ms=t.end_ms - win.start_ms) for t in toks]
                win_audio = audio[int(win.start_s * _SR):int(win.end_s * _SR)]
                plan = self._plan_truncated_tail(
                    local, win_audio, require_speech=self._recover_short_spans)
                if plan is not None:
                    tail_candidates.append((win, plan))
                else:
                    window_tokens_map[win] = local

            if tail_candidates:
                recovered_map, bs = self._batch_recover_tails(tail_candidates, common, bs)
                window_tokens_map.update(recovered_map)

            for run in long_runs:
                run_tokens_queue = [list(window_tokens_map[win]) for win in run]

                def decode_fn(_win_audio):
                    return run_tokens_queue.pop(0)

                run_windows = [
                    AudioWindow(audio[int(win.start_s * _SR):int(win.end_s * _SR)],
                                win.start_ms, win.end_ms)
                    for win in run
                ]
                logger.info("Long pause-free span %.1fs-%.1fs decoded as %d overlapping window(s)",
                            run[0].start_s, run[-1].end_s, len(run_windows))
                for tok in decode_windows(run_windows, decode_fn,
                                           seam_window_ms=int(self._window_policy.overlap_s * 1000),
                                           cut_seams=True):
                    words.append((tok.text, tok.start_ms, tok.end_ms, tok.confidence))

        words.sort(key=lambda w: w[1])
        return words

    def transcribe(self, inp: EngineInput, temperature: float | list[float] | None = None,
                    beam_size: int | None = None) -> EngineResult:
        assert self._model is not None, "load() must be called first"
        audio = self._load_array(inp)

        use_prompt = self._bias_channel in ("prompt", "both")
        initial_prompt = self._build_bias_prompt(inp) if inp.bias_terms and use_prompt else None
        self._hotwords = (self._build_hotwords(inp)
                          if inp.bias_terms and self._bias_channel in ("hotwords", "both") else None)
        self._segment_stats = []

        kwargs = {}
        if inp.speech_spans:
            kwargs["speech_spans"] = inp.speech_spans
        language = self._resolve_language(inp.language_hint, audio)
        words = self._transcribe_batched(audio, language, initial_prompt,
                                          temperature=temperature, beam_size=beam_size,
                                          **kwargs)

        cues, sub_words = split_cues(words, self._cue_policy, return_words=True)
        tokens = [
            RecognizedToken(
                text=text, start_ms=start, end_ms=end,
                confidence=conf, script=detect_script(text),
            )
            for text, start, end, conf in cues
        ]

        return EngineResult(
            tokens=tokens,
            engine_name="faster_whisper",
            timestamps_final=True,
            raw={
                "segments": list(self._segment_stats),
                "words": [
                    {"text": w.text, "start_ms": w.start_ms, "end_ms": w.end_ms, "confidence": w.confidence, "subdivided": True}
                    for w in sub_words
                ],
            },
        )

    def _release(self) -> None:
        if self._pipeline is not None:
            del self._pipeline
            self._pipeline = None
        if self._model is not None:
            del self._model
            self._model = None
        if self._pre_load_path is not None:
            os.environ["PATH"] = self._pre_load_path
            self._pre_load_path = None
        logger.info("FasterWhisper unloaded, VRAM freed")
