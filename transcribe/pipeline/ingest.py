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


def _denoise_window(window: np.ndarray, sr: int, model, df_state, enhance_fn, df_load_fn) -> np.ndarray:
    """Apply a pre-loaded DeepFilterNet model to one audio window."""
    import tempfile, os
    import soundfile as sf

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp = f.name
    try:
        sf.write(tmp, window, sr)
        audio_t, _ = df_load_fn(tmp, df_state.sr())
        enhanced = enhance_fn(model, df_state, audio_t)
        out = enhanced.squeeze().numpy() if hasattr(enhanced, "numpy") else np.array(enhanced)
        if df_state.sr() != sr:
            import librosa
            out = librosa.resample(out, orig_sr=df_state.sr(), target_sr=sr)
        return out.astype(np.float32)
    except Exception as e:
        logger.warning("Window denoise failed (%s), using original", e)
        return window
    finally:
        os.unlink(tmp)


def _apply_rolling_denoise(audio: np.ndarray, sr: int) -> np.ndarray:
    """Apply DeepFilterNet only to windows whose RMS exceeds the noise threshold."""
    try:
        from df.enhance import enhance, init_df, load_audio as df_load
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
            output[start:end] = _denoise_window(window, sr, model, df_state, enhance, df_load)
            denoised_count += 1

    if denoised_count:
        logger.info("Denoised %d/%d windows", denoised_count, num_windows)
    return output


def _vad_chunks(audio: np.ndarray, sr: int) -> list[tuple[int, int]]:
    """Run Silero VAD; return list of (start_sample, end_sample) speech segments."""
    try:
        import torch
        model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            onnx=False,
        )
        (get_speech_ts, *_) = utils
        speech_timestamps = get_speech_ts(
            torch.from_numpy(audio), model, sampling_rate=sr,
            threshold=0.5, min_speech_duration_ms=250, min_silence_duration_ms=300,
        )
        return [(s["start"], s["end"]) for s in speech_timestamps]
    except Exception as e:
        logger.warning("Silero VAD unavailable (%s), using whole file as one chunk", e)
        return [(0, len(audio))]


def ingest(path: str, denoise: bool = True) -> list[AudioChunk]:
    """
    Main ingestion entry point.
    Returns a list of speech AudioChunks (denoised, 16kHz mono float32).
    """
    logger.info("Ingesting: %s", path)
    audio, sr = load_audio(path)

    if denoise:
        audio = _apply_rolling_denoise(audio, sr)

    segments = _vad_chunks(audio, sr)
    logger.info("VAD found %d speech segments", len(segments))

    chunks = []
    for start_s, end_s in segments:
        chunk_audio = audio[start_s:end_s]
        chunks.append(AudioChunk(
            audio=chunk_audio,
            start_ms=int(start_s * 1000 / sr),
            end_ms=int(end_s * 1000 / sr),
        ))
    return chunks
