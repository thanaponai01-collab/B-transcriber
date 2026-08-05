"""Acceptance tests for tools/make_finetune_set.py (HANDOFF_ONE_ENGINE.md Phase C
step 1 — the fine-tune data engine). Covers the contamination guard (the
mechanical enforcement of Section 3.4's hold-out rule) and both ingest paths."""

import json
import tempfile
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from tools.make_finetune_set import (
    ContaminationError,
    compute_stats,
    find_contamination,
    ingest_corrections,
    ingest_srt,
    load_gold_sources,
)

_REAL_GOLD_SOURCES = Path(__file__).resolve().parents[1] / "transcribe" / "eval" / "goldenset" / "SOURCES.md"


# ── contamination guard ────────────────────────────────────────────────────────

def test_load_gold_sources_parses_real_sources_md():
    rows = load_gold_sources(_REAL_GOLD_SOURCES)
    assert len(rows) >= 8
    names = {r["gold_clip"] for r in rows}
    assert "Short1" in names
    assert any("PeterWolf" in n for n in names)


def test_find_contamination_matches_known_gold_clip_name():
    rows = load_gold_sources(_REAL_GOLD_SOURCES)
    assert find_contamination("Short1", rows) is not None


def test_find_contamination_matches_shared_source_video_token():
    rows = load_gold_sources(_REAL_GOLD_SOURCES)
    # Short1_D5 / Short2_D1 / PeterWolf all trace back to "SOUND FINAL" per SOURCES.md.
    match = find_contamination("SOUND FINAL", rows)
    assert match is not None


def test_find_contamination_none_for_unrelated_source():
    rows = load_gold_sources(_REAL_GOLD_SOURCES)
    assert find_contamination("a totally unrelated cooking vlog raw footage", rows) is None


def test_find_contamination_ignores_too_short_needle():
    rows = load_gold_sources(_REAL_GOLD_SOURCES)
    assert find_contamination("a", rows) is None


# ── fixtures ──────────────────────────────────────────────────────────────────

def _write_wav(path: Path, duration_s: float = 6.0, sr: int = 16000) -> None:
    t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False)
    audio = (0.1 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), audio, sr)


def _write_srt(path: Path) -> None:
    path.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nhello there\n\n"
        "2\n00:00:02,000 --> 00:00:04,000\nworld today\n\n",
        encoding="utf-8",
    )


# ── from-srt ────────────────────────────────────────────────────────────────────

def test_ingest_srt_writes_manifest_and_audio_slices():
    d = Path(tempfile.mkdtemp())
    audio_path = d / "clip.wav"
    srt_path = d / "clip.srt"
    _write_wav(audio_path)
    _write_srt(srt_path)
    manifest = d / "manifest.jsonl"
    data_dir = d / "data"

    result = ingest_srt(str(srt_path), str(audio_path), "unique_test_video_xyz",
                         manifest=manifest, data_dir=data_dir)

    assert result["n_utterances"] == 2
    assert result["duration_ms"] > 0
    lines = [json.loads(ln) for ln in manifest.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    assert lines[0]["text"] == "hello there"
    assert lines[0]["source"] == "unique_test_video_xyz"
    assert lines[0]["origin"] == "srt"
    assert Path(lines[0]["audio"]).exists()  # absolute path (data_dir is outside the repo root here)


def test_ingest_srt_refuses_contaminated_source_and_writes_nothing():
    d = Path(tempfile.mkdtemp())
    audio_path = d / "clip.wav"
    srt_path = d / "clip.srt"
    _write_wav(audio_path)
    _write_srt(srt_path)
    manifest = d / "manifest.jsonl"
    data_dir = d / "data"

    with pytest.raises(ContaminationError):
        ingest_srt(str(srt_path), str(audio_path), "Short1", manifest=manifest, data_dir=data_dir)

    assert not manifest.exists()
    assert not data_dir.exists()


def test_ingest_srt_skips_too_short_cues():
    d = Path(tempfile.mkdtemp())
    audio_path = d / "clip.wav"
    srt_path = d / "clip.srt"
    _write_wav(audio_path)
    srt_path.write_text(
        "1\n00:00:00,000 --> 00:00:00,050\nblink\n\n"  # 50ms, below min_cue_ms
        "2\n00:00:02,000 --> 00:00:04,000\nworld today\n\n",
        encoding="utf-8",
    )
    manifest = d / "manifest.jsonl"
    result = ingest_srt(str(srt_path), str(audio_path), "unique_test_video_short_cues",
                         manifest=manifest, data_dir=d / "data")
    assert result["n_utterances"] == 1


# ── from-corrections ─────────────────────────────────────────────────────────────

def test_ingest_corrections_pulls_corrected_text_and_slices_audio():
    from transcribe.db import store

    d = Path(tempfile.mkdtemp())
    audio_path = d / "session.wav"
    _write_wav(audio_path, duration_s=4.0)
    db_path = d / "test.db"
    store.init_db(db_path)
    conn = store.connect(db_path)

    media_id = store.create_media(conn, str(audio_path))
    job_id = store.create_job(conn, media_id, "faster_whisper", "passthrough", "v1")
    store.create_token(conn, job_id, 0, "hello there", 0, 2000, "latin", 0.9, "a")
    store.create_correction(conn, job_id, 0, "hello there", "hello there!", "a")
    conn.close()

    manifest = d / "manifest.jsonl"
    result = ingest_corrections(str(db_path), manifest=manifest, data_dir=d / "data")

    assert result["n_utterances"] == 1
    assert result["n_skipped_contaminated"] == 0
    lines = [json.loads(ln) for ln in manifest.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["text"] == "hello there!"
    assert lines[0]["origin"] == "correction"


def test_ingest_corrections_skips_contaminated_media():
    from transcribe.db import store

    d = Path(tempfile.mkdtemp())
    audio_path = d / "Short1.wav"  # filename stem matches a real gold-set clip name
    _write_wav(audio_path, duration_s=4.0)
    db_path = d / "test.db"
    store.init_db(db_path)
    conn = store.connect(db_path)

    media_id = store.create_media(conn, str(audio_path))
    job_id = store.create_job(conn, media_id, "faster_whisper", "passthrough", "v1")
    store.create_token(conn, job_id, 0, "hello there", 0, 2000, "latin", 0.9, "a")
    store.create_correction(conn, job_id, 0, "hello there", "hello there!", "a")
    conn.close()

    manifest = d / "manifest.jsonl"
    result = ingest_corrections(str(db_path), manifest=manifest, data_dir=d / "data")

    assert result["n_utterances"] == 0
    assert result["n_skipped_contaminated"] == 1


def test_ingest_corrections_skips_deletion_corrections_with_empty_text():
    from transcribe.db import store

    d = Path(tempfile.mkdtemp())
    audio_path = d / "session2.wav"
    _write_wav(audio_path, duration_s=4.0)
    db_path = d / "test.db"
    store.init_db(db_path)
    conn = store.connect(db_path)

    media_id = store.create_media(conn, str(audio_path))
    job_id = store.create_job(conn, media_id, "faster_whisper", "passthrough", "v1")
    store.create_token(conn, job_id, 0, "hallucinated filler", 0, 1000, "latin", 0.9, "a")
    store.create_correction(conn, job_id, 0, "hallucinated filler", "", "a")
    conn.close()

    manifest = d / "manifest.jsonl"
    result = ingest_corrections(str(db_path), manifest=manifest, data_dir=d / "data")
    assert result["n_utterances"] == 0


# ── stats ─────────────────────────────────────────────────────────────────────

def test_compute_stats_reports_keep_collecting_below_threshold():
    d = Path(tempfile.mkdtemp())
    manifest = d / "manifest.jsonl"
    manifest.write_text(
        json.dumps({"duration_ms": 5 * 60_000, "source": "vidA"}) + "\n",
        encoding="utf-8",
    )
    stats = compute_stats(manifest)
    assert stats["n_utterances"] == 1
    assert stats["total_minutes"] == 5.0
    assert stats["verdict"] == "keep-collecting"


def test_compute_stats_empty_manifest():
    d = Path(tempfile.mkdtemp())
    stats = compute_stats(d / "does_not_exist.jsonl")
    assert stats["n_utterances"] == 0
    assert stats["total_minutes"] == 0.0
    assert stats["verdict"] == "keep-collecting"
