"""Acceptance tests for scripts/learn_from_srt.py — the CLI that wires
align_srt's grouping into the correction table and (by default) the bias-index
promotion + regression gate.

update_bias_index's own promotion/rollback correctness is already proven in
tests/test_phase5_flywheel.py — these tests only prove learn_from_srt.py
*calls* it correctly, via monkeypatch, so this suite never has to run the real
GPU pipeline/eval harness.
"""

import builtins
import importlib.util
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location("learn_from_srt", ROOT / "scripts" / "learn_from_srt.py")
learn_from_srt = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(learn_from_srt)

from transcribe.db import store  # noqa: E402


def _make_job(tmp_dir: Path):
    media_file = tmp_dir / "clip.wav"
    media_file.write_bytes(b"not real audio, only sha256_of_file reads this")
    db_path = tmp_dir / "test.db"
    store.init_db(db_path)
    conn = store.connect(db_path)
    media_id = store.create_media(conn, str(media_file))
    job_id = store.create_job(conn, media_id, "faster_whisper", "passthrough", "v1")
    store.create_token(conn, job_id, 0, "hello", 0, 1000, "latin", 0.9, "a")
    store.create_token(conn, job_id, 1, "there world", 1000, 2000, "latin", 0.9, "a")
    conn.commit()  # create_token doesn't commit itself (batch callers commit once)
    conn.close()
    return db_path, job_id


def _write_srt(tmp_dir: Path, cue_text: str = "hello there, world") -> Path:
    srt_path = tmp_dir / "final.srt"
    srt_path.write_text(
        f"1\n00:00:00,000 --> 00:00:02,000\n{cue_text}\n\n", encoding="utf-8"
    )
    return srt_path


def test_cli_writes_corrections_with_yes_and_no_promote(monkeypatch, capsys):
    d = Path(tempfile.mkdtemp())
    db_path, job_id = _make_job(d)
    srt_path = _write_srt(d)

    monkeypatch.setattr(sys, "argv", [
        "learn_from_srt.py", str(job_id), str(srt_path),
        "--db", str(db_path), "--yes", "--no-promote",
    ])
    learn_from_srt.main()

    out = capsys.readouterr().out
    assert "1 correction(s) will be written" in out
    assert "wrote 1 correction row(s)" in out

    conn = store.connect(db_path)
    corrections = store.get_corrections(conn, job_id)
    conn.close()
    assert len(corrections) == 1
    assert corrections[0].corrected_text == "hello there, world"


def test_cli_declines_without_yes_flag_writes_nothing(monkeypatch, capsys):
    d = Path(tempfile.mkdtemp())
    db_path, job_id = _make_job(d)
    srt_path = _write_srt(d)

    monkeypatch.setattr(sys, "argv", [
        "learn_from_srt.py", str(job_id), str(srt_path), "--db", str(db_path),
    ])
    monkeypatch.setattr(builtins, "input", lambda _prompt: "n")
    learn_from_srt.main()

    out = capsys.readouterr().out
    assert "aborted" in out

    conn = store.connect(db_path)
    corrections = store.get_corrections(conn, job_id)
    conn.close()
    assert corrections == []


def test_cli_calls_update_bias_index_when_promoting(monkeypatch, capsys):
    d = Path(tempfile.mkdtemp())
    db_path, job_id = _make_job(d)
    srt_path = _write_srt(d)

    calls = []

    def _fake_update_bias_index(conn, active_engines, eval_config, db_path, run_regression_gate):
        calls.append({
            "active_engines": active_engines,
            "db_path": db_path,
            "run_regression_gate": run_regression_gate,
        })
        return ["chatgpt"]

    monkeypatch.setattr(learn_from_srt.biasindex, "update_bias_index", _fake_update_bias_index)
    monkeypatch.setattr(sys, "argv", [
        "learn_from_srt.py", str(job_id), str(srt_path), "--db", str(db_path), "--yes",
    ])
    learn_from_srt.main()

    out = capsys.readouterr().out
    assert "bias index updated — 1 active term(s)" in out
    assert len(calls) == 1
    assert calls[0]["active_engines"] == ["faster_whisper", "passthrough"]
    assert calls[0]["db_path"] == db_path
    assert calls[0]["run_regression_gate"] is True


def test_cli_reports_blocked_promotion_and_exits_nonzero(monkeypatch, capsys):
    d = Path(tempfile.mkdtemp())
    db_path, job_id = _make_job(d)
    srt_path = _write_srt(d)

    def _fake_update_bias_index(conn, active_engines, eval_config, db_path, run_regression_gate):
        raise RuntimeError("Bias update rejected by regression gate: metrics regressed")

    monkeypatch.setattr(learn_from_srt.biasindex, "update_bias_index", _fake_update_bias_index)
    monkeypatch.setattr(sys, "argv", [
        "learn_from_srt.py", str(job_id), str(srt_path), "--db", str(db_path), "--yes",
    ])
    with pytest.raises(SystemExit) as exc_info:
        learn_from_srt.main()
    assert exc_info.value.code == 1

    out = capsys.readouterr().out
    assert "bias promotion BLOCKED" in out

    # The correction row itself must survive a rejected promotion — only the
    # bias *terms* are rolled back inside update_bias_index, not the ground
    # truth we recorded.
    conn = store.connect(db_path)
    corrections = store.get_corrections(conn, job_id)
    conn.close()
    assert len(corrections) == 1


def test_cli_errors_on_unknown_job(monkeypatch):
    d = Path(tempfile.mkdtemp())
    db_path, _job_id = _make_job(d)
    srt_path = _write_srt(d)

    monkeypatch.setattr(sys, "argv", [
        "learn_from_srt.py", "9999", str(srt_path), "--db", str(db_path), "--yes",
    ])
    with pytest.raises(SystemExit, match="No tokens found"):
        learn_from_srt.main()


def test_cli_errors_on_timebase_mismatch(monkeypatch):
    d = Path(tempfile.mkdtemp())
    db_path, job_id = _make_job(d)
    # Final SRT timed against a wildly disjoint region — nothing will overlap.
    srt_path = d / "final.srt"
    srt_path.write_text(
        "1\n00:10:00,000 --> 00:10:02,000\nhello there, world\n\n", encoding="utf-8"
    )

    monkeypatch.setattr(sys, "argv", [
        "learn_from_srt.py", str(job_id), str(srt_path), "--db", str(db_path), "--yes",
    ])
    with pytest.raises(SystemExit, match="refusing to align"):
        learn_from_srt.main()
