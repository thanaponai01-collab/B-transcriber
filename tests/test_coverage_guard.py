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


def test_coverage_guard_keeps_engine_a_resident_without_reloading(monkeypatch, tmp_path):
    """When coverage_guard is enabled and engine_b is passthrough, Engine A must not reload."""
    import tempfile
    import numpy as np
    import soundfile as sf
    from transcribe.pipeline import run as pipeline_run
    from transcribe.pipeline import ingest
    from transcribe.engines.mock import MockEngine

    sr = 16000
    f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    f.close()
    # 6 seconds of audio
    sf.write(f.name, (0.2 * np.sin(np.linspace(0, 400 * np.pi, sr * 6))).astype(np.float32), sr)
    # Speech span 0 to 6000 ms -> mock engine covers 0 to 2000 ms, leaving 2000-6000 ms gap
    monkeypatch.setattr(ingest, "_load_silero",
                        lambda: (object(), lambda a, m, **k: [{"start": 0, "end": len(a)}]))

    events = []
    orig_load = MockEngine.load
    orig_unload = MockEngine.unload

    def tracking_load(self):
        events.append(("load", id(self)))
        return orig_load(self)

    def tracking_unload(self):
        events.append(("unload", id(self)))
        return orig_unload(self)

    monkeypatch.setattr(MockEngine, "load", tracking_load)
    monkeypatch.setattr(MockEngine, "unload", tracking_unload)

    cfg = {
        "engine_a": "mock",
        "engine_b": "passthrough",
        "denoise": False,
        "drop_tokens_over_silence": False,
        "coverage_guard": {"enabled": True},
    }
    tokens = pipeline_run.run_file(f.name, cfg, tmp_path / "resident.db")

    loads = [e for e in events if e[0] == "load"]
    unloads = [e for e in events if e[0] == "unload"]
    assert len(loads) == 1, f"Expected 1 load, got {len(loads)}: {events}"
    assert len(unloads) == 1, f"Expected 1 unload, got {len(unloads)}: {events}"
    assert loads[0][1] == unloads[0][1], "Load and unload must be on the same engine instance"
    assert events == [("load", loads[0][1]), ("unload", unloads[0][1])]


def test_coverage_guard_resident_unloads_on_pipeline_error(monkeypatch, tmp_path):
    """If refine() or coverage guard raises, Engine A must still be unloaded via finally."""
    import tempfile
    import numpy as np
    import soundfile as sf
    import pytest
    from transcribe.pipeline import run as pipeline_run
    from transcribe.pipeline import ingest, refine
    from transcribe.engines.mock import MockEngine

    sr = 16000
    f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    f.close()
    sf.write(f.name, (0.2 * np.sin(np.linspace(0, 400 * np.pi, sr * 6))).astype(np.float32), sr)
    monkeypatch.setattr(ingest, "_load_silero",
                        lambda: (object(), lambda a, m, **k: [{"start": 0, "end": len(a)}]))

    events = []
    orig_load = MockEngine.load
    orig_unload = MockEngine.unload

    def tracking_load(self):
        events.append(("load", id(self)))
        return orig_load(self)

    def tracking_unload(self):
        events.append(("unload", id(self)))
        return orig_unload(self)

    monkeypatch.setattr(MockEngine, "load", tracking_load)
    monkeypatch.setattr(MockEngine, "unload", tracking_unload)

    def exploding_refine(*args, **kwargs):
        raise RuntimeError("boom inside refine")

    monkeypatch.setattr(refine, "refine", exploding_refine)

    cfg = {
        "engine_a": "mock",
        "engine_b": "passthrough",
        "denoise": False,
        "drop_tokens_over_silence": False,
        "coverage_guard": {"enabled": True},
    }
    with pytest.raises(RuntimeError, match="boom inside refine"):
        pipeline_run.run_file(f.name, cfg, tmp_path / "error.db")

    loads = [e for e in events if e[0] == "load"]
    unloads = [e for e in events if e[0] == "unload"]
    assert len(loads) == 1
    assert len(unloads) == 1
    assert loads[0][1] == unloads[0][1]


def test_coverage_guard_unloads_before_second_model_when_dual_engine(monkeypatch, tmp_path):
    """When engine_b is a real engine, Engine A must unload before Engine B loads."""
    import tempfile
    import numpy as np
    import soundfile as sf
    from transcribe.pipeline import run as pipeline_run
    from transcribe.pipeline import ingest
    from transcribe.engines.mock import MockEngine

    sr = 16000
    f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    f.close()
    sf.write(f.name, (0.2 * np.sin(np.linspace(0, 400 * np.pi, sr * 6))).astype(np.float32), sr)
    monkeypatch.setattr(ingest, "_load_silero",
                        lambda: (object(), lambda a, m, **k: [{"start": 0, "end": len(a)}]))

    events = []
    orig_load = MockEngine.load
    orig_unload = MockEngine.unload

    def tracking_load(self):
        events.append(("load", self._name, id(self)))
        return orig_load(self)

    def tracking_unload(self):
        events.append(("unload", self._name, id(self)))
        return orig_unload(self)

    monkeypatch.setattr(MockEngine, "load", tracking_load)
    monkeypatch.setattr(MockEngine, "unload", tracking_unload)

    cfg = {
        "engine_a": "mock",
        "engine_b": "mock",
        "denoise": False,
        "drop_tokens_over_silence": False,
        "coverage_guard": {"enabled": True},
    }
    pipeline_run.run_file(f.name, cfg, tmp_path / "dual.db")

    # In dual engine, Engine A must be unloaded before Engine B loads
    # Sequence should be: load A -> unload A -> load B -> unload B -> (if gap redecode) load A -> unload A
    a_events = [e for e in events if e[1] == "mock"]
    load_indices = [i for i, e in enumerate(events) if e[0] == "load"]
    unload_indices = [i for i, e in enumerate(events) if e[0] == "unload"]
    # Verify unload comes before the next load
    for l_idx, u_idx in zip(load_indices, unload_indices):
        assert u_idx > l_idx
        # And before next load if there is one
    for u_idx, next_l_idx in zip(unload_indices[:-1], load_indices[1:]):
        assert u_idx < next_l_idx, "Previous engine must be unloaded before next engine loads"

