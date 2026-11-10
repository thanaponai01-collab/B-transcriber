"""Premiere transcript JSON export (cutdeck/premiere_transcript.py).

The output must validate against Adobe's transcript_format_spec.json, and `validate` must
also catch what that schema cannot: overlapping words and milliseconds written as seconds.
"""
import copy
import json
import re
import tempfile
from pathlib import Path

import numpy as np
import pytest

from cutdeck.premiere_transcript import (
    SPEAKER_ID, build_transcript, media_duration_s, transcript_for_job, validate)
from cutdeck.words import Word
from transcribe.db import store
from transcribe.pipeline import ingest

UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def _wav(seconds=3.0, sr=16000):
    import soundfile as sf
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    f.close()
    sf.write(f.name, (0.2 * np.sin(2 * np.pi * 200 * t)).astype(np.float32), sr)
    return f.name


def _mock_job(monkeypatch, raw_words=None):
    """A finished mock-engine job; `raw_words` stands in for faster-whisper's word list."""
    import transcribe.engines.mock as mock
    from transcribe.pipeline import run as pipeline_run
    if raw_words is not None:
        real = mock.MockEngine.transcribe

        def with_words(self, inp):
            result = real(self, inp)
            result.raw["words"] = raw_words
            return result
        monkeypatch.setattr(mock.MockEngine, "transcribe", with_words)
        # Only whole-file engines persist raw["words"] (engine_result.raw_words_json).
        monkeypatch.setattr(mock.MockEngine, "prefers_whole_file", True, raising=False)
    monkeypatch.setattr(ingest, "_load_silero",
                        lambda: (object(), lambda a, m, **k: [{"start": 0, "end": len(a)}]))
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    db = Path(f.name)
    store.init_db(db)
    pipeline_run.run_file(_wav(), {"engine_a": "mock", "engine_b": "passthrough",
                                   "denoise": False, "drop_tokens_over_silence": False}, db)
    conn = store.connect(db)
    return conn, store.list_jobs(conn)[0].id


def test_mock_job_exports_valid_premiere_transcript(monkeypatch):
    conn, job_id = _mock_job(monkeypatch)
    tokens = store.get_tokens(conn, job_id)
    doc = transcript_for_job(conn, job_id)
    validate(doc, media_duration_s(conn, job_id))

    # ja-jp, not th-th: only then does Premiere 26.5 caption per segment (PREMIERE_FACTS.md).
    assert doc["language"] == "ja-jp"
    assert {s["language"] for s in doc["segments"]} == {"ja-jp"}
    assert [s["id"] for s in doc["speakers"]] == [SPEAKER_ID] and UUID4.match(SPEAKER_ID)
    assert {s["speaker"] for s in doc["segments"]} == {SPEAKER_ID}
    # No raw word timeline from the mock engine: each cue is one word, in seconds.
    assert len(doc["segments"]) == len(tokens)
    for seg, tok in zip(doc["segments"], tokens):
        assert [w["text"] for w in seg["words"]] == [tok.text]
        assert seg["start"] == tok.start_ms / 1000
        assert seg["duration"] == pytest.approx((tok.end_ms - tok.start_ms) / 1000)
        assert seg["words"][-1]["eos"] is True


def test_words_group_into_cues_with_fillers_and_latin(monkeypatch):
    # Mock cues: สวัสดี 0-500, ครับ 500-900, Hello 1000-1400, world 1400-1800, นะ 1800-2000.
    raw = [{"text": "สวัสดี", "start_ms": 0, "end_ms": 500, "confidence": 0.9},
           {"text": "ครับ", "start_ms": 480, "end_ms": 900, "confidence": None},  # overlaps
           {"text": "Hello", "start_ms": 1000, "end_ms": 1400, "confidence": 0.7},
           {"text": "world", "start_ms": 1400, "end_ms": 1800, "confidence": 0.6},
           {"text": "อืม", "start_ms": 1800, "end_ms": 2000, "confidence": 0.5}]
    for w in raw:
        w["subdivided"] = True  # faster-whisper's shape: already real words
    conn, job_id = _mock_job(monkeypatch, raw)
    doc = transcript_for_job(conn, job_id, filler_lexicon=["อืม"])
    validate(doc, media_duration_s(conn, job_id))

    words = [w for s in doc["segments"] for w in s["words"]]
    assert [w["text"] for w in words] == ["สวัสดี", "ครับ", "Hello", "world", "อืม"]
    assert [w["type"] for w in words] == ["word"] * 5
    assert words[1]["start"] == 0.5 and words[1]["confidence"] == 1.0  # clamped; unknown conf
    assert words[-1]["tags"] == ["filler"] and words[0]["tags"] == []
    assert words[2]["start"] == 1.0 and words[2]["duration"] == pytest.approx(0.4)
    assert all(s["words"][-1]["eos"] and not any(w["eos"] for w in s["words"][:-1])
               for s in doc["segments"])


class _Cue:
    def __init__(self, text, start_ms, end_ms):
        self.text, self.start_ms, self.end_ms, self.confidence = text, start_ms, end_ms, 0.9


def _doc():
    return build_transcript([_Cue("ก ข", 0, 1000), _Cue("ค", 1000, 2000)],
                            [Word("ก", 0, 500, 0.9), Word("ข", 500, 1000, 0.9),
                             Word("ค", 1000, 2000, 0.9)])


def test_validate_accepts_good_output():
    validate(_doc(), duration_s=2.0)


def test_validate_rejects_missing_required_field():
    doc = _doc()
    del doc["segments"][0]["words"][0]["eos"]
    with pytest.raises(ValueError, match="schema"):
        validate(doc)


def test_validate_rejects_overlapping_words():
    doc = _doc()
    doc["segments"][0]["words"][1]["start"] = 0.25
    with pytest.raises(ValueError, match="overlaps"):
        validate(doc)


def test_validate_rejects_milliseconds():
    doc = copy.deepcopy(_doc())
    for seg in doc["segments"]:
        for item in [seg, *seg["words"]]:
            item["start"] *= 1000
            item["duration"] *= 1000
    validate(doc)  # still schema-valid: only the media length shows the unit is wrong
    with pytest.raises(ValueError, match="seconds"):
        validate(doc, duration_s=2.0)


def test_export_is_plain_json():
    text = json.dumps(_doc(), ensure_ascii=False)
    assert json.loads(text) == _doc()


def test_helper_serves_a_finished_transcribe_job(monkeypatch, tmp_path):
    import asyncio
    from cutdeck.helper import Jobs
    conn, job_id = _mock_job(monkeypatch)
    db = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    conn.close()
    monkeypatch.setattr(store, "resolve_db_path", lambda config=None: db)

    jobs = Jobs(tmp_path)
    hid = "b" * 32
    (tmp_path / hid).mkdir()
    (tmp_path / hid / "result.json").write_text(
        json.dumps({"transcript_job_id": job_id}), encoding="utf-8")
    jobs.jobs[hid] = {"job_id": hid, "job_type": "transcribe", "state": "ready",
                      "result_path": str(tmp_path / hid / "result.json")}

    reply = asyncio.run(jobs.dispatch({"type": "premiere_transcript", "job_id": hid}))
    doc = json.loads(reply["transcript"])
    validate(doc)
    assert reply["segments"] == len(doc["segments"]) == 5
    assert json.loads((tmp_path / hid / "premiere_transcript.json").read_text(encoding="utf-8")) == doc

    jobs.jobs[hid]["state"] = "running"
    with pytest.raises(ValueError, match="Transcribe the clip first"):
        asyncio.run(jobs.dispatch({"type": "premiere_transcript", "job_id": hid}))
