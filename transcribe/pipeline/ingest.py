"""Phase 2 — Ingestion: decode audio, rolling-window denoise, VAD → speech chunks.

Disposable layer — do not over-tune thresholds here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

_TARGET_SR = 16000
_WINDOW_MS = 2000        # rolling RMS window
_NOISE_DB_THRESHOLD = -35  # windows below this RMS (dB) trigger denoiser


@dataclass
class AudioChunk:
    audio: np.ndarray  # float32, 16kHz mono
    start_ms: int
    end_ms: int


@dataclass
class SpeechSpan:
    """One span of the VAD master timeline (GAP-3)."""
    idx: int
    start_ms: int
    end_ms: int
    kind: str  # 'speech' | 'silence'


@dataclass
class IngestResult:
    """Output of ingestion: the speech chunks fed to engines, plus the full
    speech/silence timeline (persisted to speech_span for CutDeck + the
    hallucination filter) and the sample rate.

    `audio` is the exact array the VAD/spans were derived from — raw for
    whole-file engines (denoise skipped), denoised when a chunk engine is active.
    run.py feeds THIS same array to the engine so the silence timeline and the
    audio the engine hears can never desync (3.2)."""
    chunks: list[AudioChunk]
    spans: list[SpeechSpan]
    sample_rate: int
    duration_ms: int
    audio: np.ndarray | None = None


_AV_CONTAINERS = frozenset({
    # Common video containers
    ".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm",
    # Broadcast / transport stream containers (ffmpeg handles these; librosa does not)
    ".ts", ".m2ts", ".mts", ".vob", ".mxf", ".ogv",
    # Audio-only containers also better served by PyAV
    ".m4a",
})


def load_audio(path: str) -> tuple[np.ndarray, int]:
    """Decode audio to 16kHz mono float32. Returns (samples, sample_rate).

    Supports WAV/FLAC/etc via librosa and all containers in _AV_CONTAINERS via PyAV.
    """
    import pathlib
    ext = pathlib.Path(path).suffix.lower()
    if ext in _AV_CONTAINERS:
        return _load_audio_av(path)
    import librosa
    try:
        audio, sr = librosa.load(path, sr=_TARGET_SR, mono=True)
        return audio.astype(np.float32), sr
    except Exception:
        return _load_audio_av(path)


def _stream_start_offset_sec(first_pts: int, time_base, container_start_us: int) -> float:
    """Seconds between the container's global t=0 and the audio stream's first
    decoded frame. MP4/AAC audio commonly starts with a small nonzero PTS
    relative to the video's presentation clock (encoder priming samples, an
    edit-list offset) — positive here means the audio stream starts *after*
    the container's t=0, which is the common case."""
    first_pts_sec = float(first_pts * time_base)
    return first_pts_sec - (container_start_us / 1_000_000.0)


def _align_audio_start(audio: np.ndarray, sr: int, offset_sec: float) -> np.ndarray:
    """Pad (or trim) so sample 0 lines up with the container's global t=0.

    Left uncorrected, every downstream ms timestamp derived from this array
    carries the same small constant offset vs. the video's actual clock — a
    systematic sync drift, not a growing one."""
    n = int(round(abs(offset_sec) * sr))
    if n == 0:
        return audio
    if offset_sec > 0:
        return np.concatenate([np.zeros(n, dtype=audio.dtype), audio])
    return audio[n:]


def _load_audio_av(path: str) -> tuple[np.ndarray, int]:
    """Decode any audio/video container via PyAV, resample to 16kHz mono."""
    import av
    chunks: list[np.ndarray] = []
    offset_sec = 0.0
    with av.open(path) as container:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            raise ValueError(f"No audio stream found in {path}")
        native_sr = stream.codec_context.sample_rate
        container_start_us = container.start_time or 0
        first_pts = None
        for frame in container.decode(stream):
            if first_pts is None and frame.pts is not None:
                first_pts = frame.pts
            # Convert to float32 ndarray, shape (channels, samples)
            arr = frame.to_ndarray().astype(np.float32)
            if arr.ndim == 2:
                arr = arr.mean(axis=0)  # mix to mono
            chunks.append(arr)
        if first_pts is not None:
            offset_sec = _stream_start_offset_sec(first_pts, stream.time_base, container_start_us)
    if not chunks:
        raise ValueError(f"No audio frames decoded from {path}")
    audio = np.concatenate(chunks)
    audio = _align_audio_start(audio, native_sr, offset_sec)
    # Resample to target SR if needed
    if native_sr != _TARGET_SR:
        import librosa
        audio = librosa.resample(audio, orig_sr=native_sr, target_sr=_TARGET_SR)
    return audio.astype(np.float32), _TARGET_SR


def _rms_db(window: np.ndarray) -> float:
    rms = np.sqrt(np.mean(window ** 2) + 1e-9)
    return 20.0 * np.log10(rms)


def _denoise_window(window: np.ndarray, sr: int, model, df_state, enhance_fn) -> np.ndarray:
    """Apply a pre-loaded DeepFilterNet model to one audio window, in-memory.

    4.4: the previous version round-tripped through a temp WAV per window
    (~1.8k file writes/hr at the 2s window size) purely to satisfy
    `load_audio`'s file-path signature. Build the tensor directly instead."""
    import torch

    try:
        df_sr = df_state.sr()
        src = window if sr == df_sr else _resample(window, sr, df_sr)
        audio_t = torch.from_numpy(src).float().unsqueeze(0)
        enhanced = enhance_fn(model, df_state, audio_t)
        out = enhanced.squeeze().numpy() if hasattr(enhanced, "numpy") else np.array(enhanced)
        if df_sr != sr:
            out = _resample(out, df_sr, sr)
        return out.astype(np.float32)
    except Exception as e:
        logger.warning("Window denoise failed (%s), using original", e)
        return window


def _resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    import librosa
    return librosa.resample(audio, orig_sr=orig_sr, target_sr=target_sr)


def _apply_rolling_denoise(audio: np.ndarray, sr: int) -> np.ndarray:
    """Apply DeepFilterNet only to windows whose RMS exceeds the noise threshold."""
    try:
        from df.enhance import enhance, init_df
        model, df_state, _ = init_df()  # load once for all windows
    except Exception as e:
        logger.warning("DeepFilterNet unavailable (%s), skipping denoise", e)
        return audio

    window_samples = int(_WINDOW_MS * sr / 1000)
    output = audio.copy()
    num_windows = max(1, len(audio) // window_samples)
    denoised_count = 0

    for i in range(num_windows):
        start = i * window_samples
        end = min(start + window_samples, len(audio))
        window = audio[start:end]
        if _rms_db(window) > _NOISE_DB_THRESHOLD:
            output[start:end] = _denoise_window(window, sr, model, df_state, enhance)
            denoised_count += 1

    if denoised_count:
        logger.info("Denoised %d/%d windows", denoised_count, num_windows)
    return output


def _load_silero():
    """Load Silero VAD. Prefer the pip package `silero-vad` (no first-run network
    fetch, no torch.hub supply-chain surface); fall back to torch.hub only if the
    package is absent. Returns (model, get_speech_timestamps_fn)."""
    try:
        from silero_vad import load_silero_vad, get_speech_timestamps
        return load_silero_vad(onnx=False), get_speech_timestamps
    except ImportError:
        import torch
        model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            onnx=False,
        )
        return model, utils[0]


def _vad_chunks(audio: np.ndarray, sr: int,
                threshold: float = 0.5,
                min_speech_ms: int = 250,
                min_silence_ms: int = 300) -> list[tuple[int, int]]:
    """Run Silero VAD; return list of (start_sample, end_sample) speech segments."""
    try:
        import torch
        model, get_speech_ts = _load_silero()
        speech_timestamps = get_speech_ts(
            torch.from_numpy(audio), model, sampling_rate=sr,
            threshold=threshold,
            min_speech_duration_ms=min_speech_ms,
            min_silence_duration_ms=min_silence_ms,
        )
        return [(s["start"], s["end"]) for s in speech_timestamps]
    except Exception as e:
        logger.warning("Silero VAD unavailable (%s), using whole file as one chunk", e)
        return [(0, len(audio))]


_FLOOR_DB_FALLBACK = -55.0     # used only when a file has too little speech to estimate from
_FLOOR_DB_MIN = -80.0          # clamp: never gate this aggressively even on a very clean file
_FLOOR_DB_MAX = -35.0          # clamp: never gate this leniently even on a very noisy file


def _estimate_speech_floor_db(
    audio: np.ndarray, sr: int, segments: list[tuple[int, int]],
    percentile: float = 10.0, window_ms: int = 50,
) -> float:
    """Per-file noise floor: the ``percentile``-th quietest 50ms window *within
    VAD-flagged speech segments* (not the whole file — real cut silence would
    just pull this down to the digital floor and defeat the estimate).

    A fixed dB threshold is calibrated to one recording's gain staging; a
    quieter room mic or a hotter on-camera preamp shifts the whole noise floor
    and needs a different number. Sampling from this file's own quietest
    "speech" content instead means the gate self-calibrates per file. Clamped
    to [_FLOOR_DB_MIN, _FLOOR_DB_MAX] so a pathological file (near-silent or
    all-loud) can't make the gate absurdly aggressive or a no-op.
    """
    window = max(1, int(window_ms * sr / 1000))
    vals: list[float] = []
    for start_s, end_s in segments:
        seg = audio[start_s:end_s]
        for i in range(0, len(seg) - window, window):
            vals.append(_rms_db(seg[i:i + window]))
    if len(vals) < 20:  # not enough speech to estimate anything meaningful from
        return _FLOOR_DB_FALLBACK
    floor = float(np.percentile(vals, percentile))
    return max(_FLOOR_DB_MIN, min(_FLOOR_DB_MAX, floor))


def _rms_gate_segments(
    audio: np.ndarray, sr: int, segments: list[tuple[int, int]],
    floor_db: float = -55.0, min_gap_ms: int = 300, window_ms: int = 50,
) -> list[tuple[int, int]]:
    """Sub-split each VAD speech segment wherever raw RMS energy drops below
    ``floor_db`` for at least ``min_gap_ms`` — independent of ``vad_threshold``.

    Silero VAD is a probability model: at the low threshold Thai particle
    survival needs (0.35), it happily calls extended stretches of near-silent
    room tone "speech" as long as *something* voice-shaped is present nearby,
    producing multi-second "speech" spans that are audibly mostly dead air.
    Raising the threshold to fix that re-clips soft particles (measured
    regression, see config.yaml). This is a second, orthogonal signal — plain
    loudness — so it only removes stretches that are quiet by any measure,
    without touching VAD's voice/no-voice judgement at segment edges (where
    the particle-survival tuning actually matters).
    """
    window = max(1, int(window_ms * sr / 1000))
    min_windows = max(1, int(min_gap_ms / window_ms))
    out: list[tuple[int, int]] = []
    for start_s, end_s in segments:
        seg = audio[start_s:end_s]
        n = len(seg)
        if n <= 0:
            continue
        below = [_rms_db(seg[i:i + window]) < floor_db for i in range(0, n, window)]
        gaps: list[tuple[int, int]] = []
        run_start = None
        run_len = 0
        for wi, is_quiet in enumerate(below + [False]):  # sentinel flushes trailing run
            if is_quiet:
                if run_start is None:
                    run_start = wi
                run_len += 1
            else:
                if run_start is not None and run_len >= min_windows:
                    gaps.append((run_start * window, min(n, wi * window)))
                run_start = None
                run_len = 0
        if not gaps:
            out.append((start_s, end_s))
            continue
        cursor = 0
        for a, b in gaps:
            if a > cursor:
                out.append((start_s + cursor, start_s + a))
            cursor = b
        if cursor < n:
            out.append((start_s + cursor, start_s + n))
    return out


def _build_spans(segments: list[tuple[int, int]], total_samples: int, sr: int) -> list[SpeechSpan]:
    """Turn VAD speech segments into a gap-free, ordered speech/silence timeline
    covering [0, total]. The silence between/around speech is the master timeline
    CutDeck cuts against and the silence-overlap hallucination filter consults."""
    def to_ms(s: int) -> int:
        return int(s * 1000 / sr)

    spans: list[SpeechSpan] = []
    cursor = 0
    idx = 0
    for start_s, end_s in segments:
        start_s = max(0, min(start_s, total_samples))
        end_s = max(0, min(end_s, total_samples))
        if start_s > cursor:
            spans.append(SpeechSpan(idx, to_ms(cursor), to_ms(start_s), "silence"))
            idx += 1
        if end_s > start_s:
            spans.append(SpeechSpan(idx, to_ms(start_s), to_ms(end_s), "speech"))
            idx += 1
        cursor = max(cursor, end_s)
    if total_samples > cursor:
        spans.append(SpeechSpan(idx, to_ms(cursor), to_ms(total_samples), "silence"))
    return spans


def _materialize_chunks(audio: np.ndarray, sr: int,
                        segments: list[tuple[int, int]],
                        overlap_ms: int) -> list[AudioChunk]:
    """Cut speech chunks, extending each window by `overlap_ms` on both sides so
    adjacent chunks overlap (GAP-4). The engine then transcribes each boundary
    word in both chunks and stitch.py drops the duplicate — words are no longer
    lost at segment seams. start_ms is the extended window's true global start, so
    run.py's token offset stays correct."""
    overlap = int(overlap_ms * sr / 1000)
    n = len(audio)
    chunks = []
    for start_s, end_s in segments:
        a = max(0, start_s - overlap)
        b = min(n, end_s + overlap)
        chunks.append(AudioChunk(
            audio=audio[a:b],
            start_ms=int(a * 1000 / sr),
            end_ms=int(b * 1000 / sr),
        ))
    return chunks


def ingest(path: str, denoise: bool = True,
           vad_threshold: float = 0.5,
           vad_min_speech_ms: int = 250,
           vad_min_silence_ms: int = 300,
           rms_gate_enabled: bool = True,
           rms_gate_floor_db: float | None = None,
           rms_gate_floor_percentile: float = 10.0,
           rms_gate_min_gap_ms: int = 300,
           audio: np.ndarray | None = None,
           sr: int | None = None,
           materialize_chunks: bool = True,
           chunk_overlap_ms: int = 0) -> IngestResult:
    """
    Main ingestion entry point.

    Returns an IngestResult: speech AudioChunks plus the full VAD speech/silence
    timeline (GAP-3), the sample rate, and the array the timeline was derived from.

    `audio`/`sr`: pass a pre-decoded array to avoid re-decoding (3.2 — run.py
    decodes once). `materialize_chunks=False` skips chunk cutting entirely (whole-
    file engines don't need them — only the span timeline). `chunk_overlap_ms`
    (>0) makes adjacent chunks overlap so stitch.py can dedupe seam words.

    `rms_gate_floor_db=None` (default) estimates the gate's loudness floor from
    this file's own quietest speech content (`_estimate_speech_floor_db`) instead
    of using one fixed number for every recording — pass a float to pin it.
    """
    logger.info("Ingesting: %s", path)
    if audio is None:
        audio, sr = load_audio(path)

    if denoise:
        audio = _apply_rolling_denoise(audio, sr)

    segments = _vad_chunks(
        audio, sr,
        threshold=vad_threshold,
        min_speech_ms=vad_min_speech_ms,
        min_silence_ms=vad_min_silence_ms,
    )
    logger.info("VAD found %d speech segments", len(segments))

    if rms_gate_enabled:
        floor_db = rms_gate_floor_db
        if floor_db is None:
            floor_db = _estimate_speech_floor_db(audio, sr, segments,
                                                 percentile=rms_gate_floor_percentile)
            logger.info("RMS gate: estimated floor %.1f dB (p%.0f of speech content)",
                        floor_db, rms_gate_floor_percentile)
        gated = _rms_gate_segments(audio, sr, segments,
                                   floor_db=floor_db,
                                   min_gap_ms=rms_gate_min_gap_ms)
        if len(gated) != len(segments):
            logger.info("RMS gate split %d VAD segment(s) into %d",
                        len(segments), len(gated))
        segments = gated

    chunks = _materialize_chunks(audio, sr, segments, chunk_overlap_ms) if materialize_chunks else []

    spans = _build_spans(segments, len(audio), sr)
    return IngestResult(
        chunks=chunks,
        spans=spans,
        sample_rate=sr,
        duration_ms=int(len(audio) * 1000 / sr),
        audio=audio,
    )
