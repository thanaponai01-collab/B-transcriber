"""Phase 2 acceptance — sequence-mixdown ingest path
(docs/HANDOFF_CUTDECK_LIVE_SEQUENCE.md).

A synthetic multi-silence WAV run through ingest() -> build_cut_spans() must
produce a CutPlan whose CUT spans match hand-computed expected silence regions,
using the same silence-cut padding math as tests/test_cutdeck_phase1.py.

No ASR engine may be imported or run by this path — a transcription-free run
must work end-to-end (silence-only removal).
"""

import logging
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from cutdeck.contracts import CUT, KEEP, CutConfig  # noqa: E402
from cutdeck.sequence_mixdown import plan_from_mixdown  # noqa: E402
from transcribe.pipeline import ingest as ingest_mod  # noqa: E402

SR = 16000


def _synthetic_multi_silence_wav():
    """speech[0-1.5s] silence[1.5-3.0s] speech[3.0-4.0s] silence[4.0-5.5s] speech[5.5-6.5s].

    Both silences are 1500ms, above the default min_silence_ms=900.
    """
    import soundfile as sf

    def loud(seconds):
        t = np.linspace(0, seconds, int(SR * seconds), endpoint=False)
        return (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)

    def quiet(seconds):
        return np.zeros(int(SR * seconds), dtype=np.float32)

    audio = np.concatenate([loud(1.5), quiet(1.5), loud(1.0), quiet(1.5), loud(1.0)])
    f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    f.close()
    sf.write(f.name, audio, SR)
    return f.name, audio


def _stub_speech_timestamps_from_samples(samples: np.ndarray):
    """Deterministic get_speech_timestamps-alike: returns the exact sample
    boundaries used to build the synthetic wav, in Silero's dict-list shape."""
    def fn(tensor, model, **kwargs):
        arr = tensor.numpy() if hasattr(tensor, "numpy") else np.asarray(tensor)
        # Recover boundaries directly from the known construction rather than
        # a real energy threshold — this stub exists to make the VAD step
        # deterministic, not to test VAD itself.
        bounds_s = [(0.0, 1.5), (3.0, 4.0), (5.5, 6.5)]
        return [{"start": int(s * SR), "end": int(e * SR)} for s, e in bounds_s]
    return fn


@pytest.fixture
def mixdown_path(monkeypatch):
    path, audio = _synthetic_multi_silence_wav()
    monkeypatch.setattr(
        ingest_mod, "_load_silero",
        lambda: (object(), _stub_speech_timestamps_from_samples(audio)),
    )
    yield path


def test_silence_only_removal_matches_hand_computed_regions(mixdown_path):
    cfg = CutConfig()  # defaults: min_silence_ms=900, pad_pre_ms=250, pad_post_ms=120
    plan = plan_from_mixdown(
        mixdown_path, job_id=1, cfg=cfg, rms_gate_enabled=False,
    )

    cuts = [s for s in plan.spans if s.action == CUT]
    assert len(cuts) == 2

    # silence_cuts(): cut_start = silence_start + pad_post_ms, cut_end = silence_end - pad_pre_ms
    expected = [
        (1500 + cfg.pad_post_ms, 3000 - cfg.pad_pre_ms),
        (4000 + cfg.pad_post_ms, 5500 - cfg.pad_pre_ms),
    ]
    for (exp_start, exp_end), cut in zip(expected, cuts):
        assert abs(cut.src_in_ms - exp_start) <= 5
        assert abs(cut.src_out_ms - exp_end) <= 5
        assert cut.reason == "silence"

    # Plan tiles the whole media duration (build_plan's invariant already
    # asserts this internally; re-check duration matches the source).
    assert plan.duration_ms == pytest.approx(6500, abs=5)


def test_no_asr_engine_imported(mixdown_path):
    """Transcription-free: no engines.* module may be imported by this path."""
    import sys as _sys

    before = {m for m in _sys.modules if m.startswith("engines")}
    cfg = CutConfig()
    plan_from_mixdown(mixdown_path, job_id=1, cfg=cfg, rms_gate_enabled=False)
    after = {m for m in _sys.modules if m.startswith("engines")}
    assert after == before


def test_fillers_enabled_degrades_to_silence_only_with_warning(mixdown_path, caplog):
    cfg = CutConfig(fillers_enabled=True)
    with caplog.at_level(logging.WARNING):
        plan = plan_from_mixdown(mixdown_path, job_id=1, cfg=cfg, rms_gate_enabled=False)

    assert any("degrading" in r.message for r in caplog.records)
    # Still produces a valid silence-only plan (build_plan's assertion alone
    # confirms the run didn't crash and the tiling invariant holds).
    assert any(s.action == CUT for s in plan.spans)


def test_repeats_enabled_degrades_to_silence_only_with_warning(mixdown_path, caplog):
    cfg = CutConfig(repeats_enabled=True)
    with caplog.at_level(logging.WARNING):
        plan = plan_from_mixdown(mixdown_path, job_id=1, cfg=cfg, rms_gate_enabled=False)

    assert any("degrading" in r.message for r in caplog.records)
    assert any(s.action == CUT for s in plan.spans)
