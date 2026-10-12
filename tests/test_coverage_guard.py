from transcribe.pipeline import coverage


def cue(t, s, e):
    return {"text": t, "start_ms": s, "end_ms": e}


def test_find_gaps_reports_uncovered_speech_only():
    spans = [(0, 5000), (8000, 8400)]
    cues = [cue("a", 0, 1000), cue("b", 3500, 5000), cue("c", 8000, 8400)]
    assert [g.to_dict() for g in coverage.find_gaps(spans, cues)] == [
        {"start_ms": 1000, "end_ms": 3500}]


def test_short_uncovered_speech_is_not_a_gap():
    assert coverage.find_gaps([(0, 1000)], [cue("a", 0, 500)]) == []


def test_orphan_next_to_gap():
    cues = [cue("น", 97120, 97240), cue("x", 100000, 101000)]
    gaps = coverage.find_gaps([(96000, 97300)], [cues[0]])
    assert coverage.find_orphans(cues, gaps) == [0]


def test_fill_gaps_keeps_only_tokens_inside_gap_and_never_invents():
    cues = [cue("a", 0, 1000)]
    gaps = [coverage.Gap(1000, 3000), coverage.Gap(6000, 7000)]
    calls = []

    def redecode(lo, hi):
        calls.append((lo, hi))
        if lo < 2000:
            return [cue("a", 0, 1000), cue("ยอด 500", 1200, 2800)]  # first one is context
        return []

    out, empty = coverage.fill_gaps(cues, gaps, redecode)
    assert [c["text"] for c in out] == ["a", "ยอด 500"]
    assert [g.to_dict() for g in empty] == [{"start_ms": 6000, "end_ms": 7000}]
    assert calls == [(0, 4000), (5000, 8000)]


def test_pipeline_refills_a_gap_when_guard_enabled(monkeypatch, tmp_path):
    """Wiring: run_file_job -> find_gaps -> Engine A re-decode -> tokens written."""
    import tempfile
    from contextlib import contextmanager

    import numpy as np
    import soundfile as sf

    import transcribe.engines.mock  # noqa: F401
    from transcribe.db import store
    from transcribe.pipeline import engine_run, ingest
    from transcribe.pipeline import run as pipeline_run

    sr = 16000
    f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    f.close()
    sf.write(f.name, (0.2 * np.sin(np.linspace(0, 400 * np.pi, sr * 6))).astype(np.float32), sr)
    monkeypatch.setattr(ingest, "_load_silero",
                        lambda: (object(), lambda a, m, **k: [{"start": 0, "end": len(a)}]))
    asked = []

    @contextmanager
    def fake_redecoder(plan, device, config, audio, sample_rate):
        def redecode(lo, hi):
            asked.append((lo, hi))
            return [{"text": "เติม", "start_ms": lo + 1000, "end_ms": lo + 1500,
                     "script": "thai", "confidence": 0.9}]
        yield redecode

    monkeypatch.setattr(engine_run, "gap_redecoder", fake_redecoder)
    cfg = {"engine_a": "mock", "engine_b": "passthrough", "denoise": True,
           "drop_tokens_over_silence": False, "coverage_guard": {"enabled": True}}
    off = pipeline_run.run_file(f.name, dict(cfg, coverage_guard={"enabled": False}),
                                tmp_path / "a.db")
    assert asked == []
    on = pipeline_run.run_file(f.name, cfg, tmp_path / "b.db")
    assert asked, "the guard should have found uncovered speech in the mock transcript"
    assert len(on) > len(off) and any(t["text"] == "เติม" for t in on)
