"""Phase 7 acceptance — gold-set draft/freeze round-trip (GAP-6).

Run: python -m pytest tests/test_phase7_makegold.py -v
"""

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import make_gold


def _synth_clip(dirpath: Path, stem="clip", seconds=1.0):
    import soundfile as sf
    t = np.linspace(0, seconds, int(16000 * seconds), endpoint=False)
    p = dirpath / f"{stem}.wav"
    sf.write(p, (0.2 * np.sin(2 * np.pi * 200 * t)).astype(np.float32), 16000)
    return p


# ── validate() mechanics ──────────────────────────────────────────────────────

def test_validate_accepts_clean_tokens():
    toks = [
        {"text": "สวัสดี", "script": "thai", "start_ms": 0, "end_ms": 500},
        {"text": "Hello", "script": "latin", "start_ms": 500, "end_ms": 900},
    ]
    assert make_gold.validate(toks) == []


def test_validate_catches_non_monotonic_time():
    toks = [
        {"text": "a", "script": "latin", "start_ms": 500},
        {"text": "b", "script": "latin", "start_ms": 100},  # goes backwards
    ]
    assert any("monotonic" in e for e in make_gold.validate(toks))


def test_validate_catches_script_mismatch():
    toks = [{"text": "Hello", "script": "thai", "start_ms": 0}]  # Latin tagged thai
    assert any("detect_script" in e for e in make_gold.validate(toks))


# ── freeze() safety ───────────────────────────────────────────────────────────

def test_freeze_refuses_overwrite_without_force():
    d = Path(tempfile.mkdtemp())
    toks = [{"text": "hi", "script": "latin", "start_ms": 0, "end_ms": 100}]
    _synth_clip(d)
    draft = make_gold.write_draft(str(d / "clip.wav"), toks, goldenset=d)
    make_gold.freeze(str(draft))                       # first freeze ok
    # re-draft and try to freeze again over the frozen file
    draft2 = make_gold.write_draft(str(d / "clip.wav"), toks, goldenset=d)
    with pytest.raises(FileExistsError):
        make_gold.freeze(str(draft2))
    make_gold.freeze(str(draft2), force=True)          # force overwrites


# ── end-to-end: draft → hand-edit → freeze → harness consumes ─────────────────

def test_round_trip_harness_records_baseline(monkeypatch):
    from transcribe.db import store
    from transcribe.eval import harness

    gold = Path(tempfile.mkdtemp())
    _synth_clip(gold, stem="clip")

    # draft (as if pulled from a corrected editor job)
    tokens = [
        {"text": "สวัสดี", "script": "thai", "start_ms": 0, "end_ms": 500},
        {"text": "โลก", "script": "thai", "start_ms": 500, "end_ms": 900},
    ]
    draft = make_gold.write_draft(str(gold / "clip.wav"), tokens, goldenset=gold)

    # human hand-edits one token in the JSON
    data = json.loads(draft.read_text(encoding="utf-8"))
    data["tokens"][1]["text"] = "โลกา"
    draft.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    frozen = make_gold.freeze(str(draft))
    assert frozen.exists() and frozen.name == "clip.json"

    # harness consumes the frozen gold and records a real baseline
    monkeypatch.setattr(harness, "_GOLDENSET", gold)
    db = Path(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
    store.init_db(db)
    hyp = [{"text": "สวัสดี", "script": "thai", "start_ms": 0, "end_ms": 500},
           {"text": "โลกา", "script": "thai", "start_ms": 500, "end_ms": 900}]
    result = harness.run_harness({"engine_a": "x", "engine_b": "y"}, db,
                                 pipeline_fn=lambda a, c: hyp)
    assert result is not None and result.passed
    conn = store.connect(db)
    assert store.get_last_passing_eval(conn) is not None   # a real baseline exists now
    conn.close()


# ── parse_srt (SRT → gold tokens, the hand-corrected-SRT shortcut) ────────────

def test_parse_srt_parses_cues_with_bom_and_scripts():
    srt = (
        "﻿1\n00:00:00,000 --> 00:00:02,580\nสวัสดีครับ\n\n"
        "2\n00:00:02,580 --> 00:00:04,340\nHello world\n\n"
    )
    toks = make_gold.parse_srt(srt)
    assert toks == [
        {"text": "สวัสดีครับ", "script": "thai", "start_ms": 0, "end_ms": 2580},
        {"text": "Hello world", "script": "latin", "start_ms": 2580, "end_ms": 4340},
    ]


def test_parse_srt_joins_multiline_cue_text():
    srt = "1\n00:00:01,000 --> 00:00:02,000\nline one\nline two\n\n"
    toks = make_gold.parse_srt(srt)
    assert toks[0]["text"] == "line one line two"


def test_parse_srt_output_passes_validate():
    srt = "1\n00:00:00,000 --> 00:00:01,000\nโลก\n\n2\n00:00:01,000 --> 00:00:02,000\nEarth\n\n"
    toks = make_gold.parse_srt(srt)
    assert make_gold.validate(toks) == []


def test_goldenset_discovers_video_container_audio(monkeypatch):
    """A gold sample's source clip is often a raw video export (.mp4), not
    audio-only — the harness must not silently skip it (real bug: Bangkok
    Festivals clip is .mp4 and was invisible to the old .wav/.mp3/.flac/.m4a list)."""
    from transcribe.eval import harness

    d = Path(tempfile.mkdtemp())
    (d / "clip.json").write_text(
        json.dumps({"tokens": [{"text": "hi", "script": "latin",
                                 "start_ms": 0, "end_ms": 100}]}),
        encoding="utf-8",
    )
    (d / "clip.mp4").write_bytes(b"not real video, existence is all that matters here")
    monkeypatch.setattr(harness, "_GOLDENSET", d)
    samples = harness._load_goldenset()
    assert len(samples) == 1
    assert samples[0][0] == d / "clip.mp4"


def test_from_srt_round_trip_writes_valid_draft():
    d = Path(tempfile.mkdtemp())
    _synth_clip(d, stem="clip")
    srt_path = d / "clip.srt"
    srt_path.write_text(
        "1\n00:00:00,000 --> 00:00:00,500\nสวัสดี\n\n"
        "2\n00:00:00,500 --> 00:00:00,900\nโลก\n\n",
        encoding="utf-8",
    )
    tokens = make_gold.parse_srt(srt_path.read_text(encoding="utf-8-sig"))
    draft = make_gold.write_draft(str(d / "clip.wav"), tokens, goldenset=d)
    frozen = make_gold.freeze(str(draft))
    assert frozen.name == "clip.json"
