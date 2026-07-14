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


def _load_audio_av(path: str) -> tuple[np.ndarray, int]:
    """Decode any audio/video container via PyAV, resample to 16kHz mono."""
    import av
    import fractions
    chunks: list[np.ndarray] = []
    with av.open(path) as container:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            raise ValueError(f"No audio stream found in {path}")
        native_sr = stream.codec_context.sample_rate
        for frame in container.decode(stream):
            # Convert to float32 ndarray, shape (channels, samples)
            arr = frame.to_ndarray().astype(np.float32)
            if arr.ndim == 2:
                arr = arr.mean(axis=0)  # mix to mono
            chunks.append(arr)
    if not chunks:
        raise ValueError(f"No audio frames decoded from {path}")
    audio = np.concatenate(chunks)
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

    chunks = _materialize_chunks(audio, sr, segments, chunk_overlap_ms) if materialize_chunks else []

    spans = _build_spans(segments, len(audio), sr)
    return IngestResult(
        chunks=chunks,
        spans=spans,
        sample_rate=sr,
        duration_ms=int(len(audio) * 1000 / sr),
        audio=audio,
    )
