"""Phase 3 acceptance — ingest cleanup (single decode, overlap chunks).

Run: python -m pytest tests/test_phase3_ingest.py -v
"""

import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe.pipeline import ingest


def _synthetic_wav(seconds=3.0, sr=16000):
    import soundfile as sf
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    sig = (0.2 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)
    f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    f.close()
    sf.write(f.name, sig, sr)
    return f.name


# ── 3.2 ingest emits overlapping chunks (GAP-4) ───────────────────────────────

def test_materialize_chunks_produce_overlap():
    sr = 16000
    audio = np.zeros(sr * 3, dtype=np.float32)
    # Two speech segments with a 200 ms gap between them.
    segments = [(0, sr), (int(1.2 * sr), 2 * sr)]  # [0–1000ms], [1200–2000ms]
    chunks = ingest._materialize_chunks(audio, sr, segments, overlap_ms=750)
    assert len(chunks) == 2
    # 750 ms overlap on each side closes the 200 ms gap → the two chunks overlap.
    assert chunks[0].end_ms > chunks[1].start_ms, "adjacent chunks must overlap for stitch"


def test_zero_overlap_keeps_chunks_disjoint():
    sr = 16000
    audio = np.zeros(sr * 3, dtype=np.float32)
    segments = [(0, sr), (int(1.2 * sr), 2 * sr)]
    chunks = ingest._materialize_chunks(audio, sr, segments, overlap_ms=0)
    assert chunks[0].end_ms <= chunks[1].start_ms


def test_ingest_returns_the_array_it_used(monkeypatch):
    # With denoise off, ingest must return the exact decoded array (so run.py can
    # feed the engine the same samples the VAD saw).
    monkeypatch.setattr(ingest, "_load_silero",
                        lambda: (object(), lambda a, m, **k: [{"start": 0, "end": len(a)}]))
    path = _synthetic_wav()
    audio, sr = ingest.load_audio(path)
    res = ingest.ingest(path, denoise=False, audio=audio, sr=sr, materialize_chunks=False)
    assert res.audio is audio
    assert res.chunks == []          # whole-file mode skips chunk materialization
    assert len(res.spans) >= 1       # timeline still built


# ── RMS silence gate (2026-08-03) ──────────────────────────────────────────────

def test_rms_gate_splits_quiet_stretch_inside_a_speech_segment():
    """A VAD 'speech' segment that goes near-silent in the middle for longer than
    min_gap_ms must be split into two — this is the real-world bug where a
    multi-second span reads as continuous 'speech' to VAD (threshold tuned low
    for Thai particle survival) despite an audible dead patch in the middle."""
    sr = 16000
    loud = (0.2 * np.sin(2 * np.pi * 200 * np.linspace(0, 1, sr, endpoint=False))).astype(np.float32)
    quiet = np.zeros(int(0.5 * sr), dtype=np.float32)  # 500ms of true silence
    audio = np.concatenate([loud, quiet, loud])
    segments = [(0, len(audio))]  # VAD called the whole thing one speech segment
    gated = ingest._rms_gate_segments(audio, sr, segments, floor_db=-55.0, min_gap_ms=300)
    assert len(gated) == 2
    assert gated[0][1] < gated[1][0]  # a gap was removed between them


def test_rms_gate_leaves_continuously_loud_segment_untouched():
    sr = 16000
    loud = (0.2 * np.sin(2 * np.pi * 200 * np.linspace(0, 2, 2 * sr, endpoint=False))).astype(np.float32)
    segments = [(0, len(loud))]
    gated = ingest._rms_gate_segments(loud, sr, segments, floor_db=-55.0, min_gap_ms=300)
    assert gated == segments


def test_estimate_speech_floor_scales_with_recording_loudness():
    """A fixed dB threshold miscalibrates across recordings with different gain
    staging. The estimate must track each file's own loudness instead of
    returning the same number regardless of input level."""
    sr = 16000
    rng = np.random.default_rng(0)

    def make(loud_amp, quiet_amp, n_windows=40, window_ms=50):
        win = int(window_ms * sr / 1000)
        parts = []
        for i in range(n_windows):
            amp = loud_amp if i % 2 == 0 else quiet_amp
            parts.append((amp * rng.standard_normal(win)).astype(np.float32))
        return np.concatenate(parts)

    quiet_recording = make(0.02, 0.002)   # e.g. a hot preamp, low overall level
    loud_recording = make(0.5, 0.05)      # e.g. a close mic, high overall level
    segments_q = [(0, len(quiet_recording))]
    segments_l = [(0, len(loud_recording))]

    floor_q = ingest._estimate_speech_floor_db(quiet_recording, sr, segments_q)
    floor_l = ingest._estimate_speech_floor_db(loud_recording, sr, segments_l)
    assert floor_q < floor_l, "quieter recording must get a lower (stricter) floor"


def test_estimate_speech_floor_falls_back_when_too_little_speech():
    sr = 16000
    audio = np.zeros(100, dtype=np.float32)
    floor = ingest._estimate_speech_floor_db(audio, sr, [(0, 100)])
    assert floor == ingest._FLOOR_DB_FALLBACK


def test_rms_gate_ignores_dips_shorter_than_min_gap_ms():
    sr = 16000
    loud = (0.2 * np.sin(2 * np.pi * 200 * np.linspace(0, 1, sr, endpoint=False))).astype(np.float32)
    brief_quiet = np.zeros(int(0.1 * sr), dtype=np.float32)  # 100ms — under min_gap_ms
    audio = np.concatenate([loud, brief_quiet, loud])
    segments = [(0, len(audio))]
    gated = ingest._rms_gate_segments(audio, sr, segments, floor_db=-55.0, min_gap_ms=300)
    assert gated == segments


# ── 3.2 pipeline decodes the audio exactly once per job ───────────────────────

def test_pipeline_decodes_audio_once(monkeypatch):
    """load_audio must be called exactly once per run_file (was up to 3×)."""
    import transcribe.engines.mock  # noqa: F401
    from transcribe.pipeline import run as pipeline_run
    from transcribe.db import store

    calls = {"n": 0}
    real_load = ingest.load_audio

    def spy(path):
        calls["n"] += 1
        return real_load(path)

    monkeypatch.setattr(ingest, "load_audio", spy)
    # Deterministic single-segment VAD, no real Silero/denoise.
    monkeypatch.setattr(ingest, "_load_silero",
                        lambda: (object(), lambda a, m, **k: [{"start": 0, "end": len(a)}]))

    path = _synthetic_wav()
    db = Path(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
    store.init_db(db)

    # mock engine sets timestamps_final=True → no forced-align reload path.
    cfg = {"engine_a": "mock", "engine_b": "passthrough", "denoise": True,
           "drop_tokens_over_silence": False}
    pipeline_run.run_file(path, cfg, db)

    assert calls["n"] == 1, f"expected 1 decode, got {calls['n']}"


# ── mp4/AV container start-time alignment (sync drift fix) ────────────────────

def test_stream_start_offset_sec_positive_when_audio_starts_after_container():
    from fractions import Fraction
    # first frame pts=20992 @ 1/44100 tb ≈ 0.476s, container t=0 → audio starts late.
    off = ingest._stream_start_offset_sec(20992, Fraction(1, 44100), container_start_us=0)
    assert abs(off - 0.4760) < 1e-3


def test_stream_start_offset_sec_zero_when_aligned():
    from fractions import Fraction
    off = ingest._stream_start_offset_sec(0, Fraction(1, 44100), container_start_us=0)
    assert off == 0.0


def test_align_audio_start_pads_leading_silence_for_positive_offset():
    sr = 16000
    audio = np.ones(sr, dtype=np.float32)  # 1s of signal
    aligned = ingest._align_audio_start(audio, sr, offset_sec=0.5)
    assert len(aligned) == sr + sr // 2
    assert np.all(aligned[: sr // 2] == 0.0)
    assert np.all(aligned[sr // 2 :] == 1.0)


def test_align_audio_start_trims_for_negative_offset():
    sr = 16000
    audio = np.ones(sr, dtype=np.float32)
    aligned = ingest._align_audio_start(audio, sr, offset_sec=-0.25)
    assert len(aligned) == sr - sr // 4


def test_align_audio_start_noop_for_zero_offset():
    sr = 16000
    audio = np.ones(sr, dtype=np.float32)
    aligned = ingest._align_audio_start(audio, sr, offset_sec=0.0)
    assert aligned is audio


def _mp4_with_offset_audio(out_path: str, offset_s: float = 0.5) -> None:
    """A real mp4 fixture where the audio stream's decoded PTS starts
    `offset_s` after the container's t=0 (mirrors AAC encoder-priming/edit-list
    desync seen on real footage) — built with ffmpeg lavfi sources, no
    external media needed."""
    import shutil
    import subprocess

    if shutil.which("ffmpeg") is None:
        import pytest
        pytest.skip("ffmpeg not on PATH")
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "testsrc=duration=3:size=64x64:rate=5",
        "-itsoffset", str(offset_s),
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2.5",
        "-map", "0:v", "-map", "1:a", "-shortest",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", out_path,
    ]
    subprocess.run(cmd, check=True)


def test_load_audio_av_aligns_late_starting_audio_stream(tmp_path):
    out = str(tmp_path / "offset.mp4")
    _mp4_with_offset_audio(out, offset_s=0.5)

    audio, sr = ingest._load_audio_av(out)
    assert sr == ingest._TARGET_SR

    # The leading ~0.5s (encoder priming rounds it slightly) must be the
    # padded silence, not sine-tone signal — RMS near zero.
    lead = audio[: int(0.3 * sr)]
    assert np.sqrt(np.mean(lead ** 2)) < 1e-4

    # Well past the offset, the actual sine tone must be present.
    body = audio[int(0.7 * sr): int(1.2 * sr)]
    assert np.sqrt(np.mean(body ** 2)) > 0.01
