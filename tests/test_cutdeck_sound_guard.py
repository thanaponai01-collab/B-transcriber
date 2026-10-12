"""Rough Cut must cut silence only: audible sound (a held "ahhh", a fading tail) is never cut.

The failure: Silero VAD plus the RMS gate decide "speech", and a sustained vowel can
score as non-speech, so it fell into a silence span and was cut. The guard reclaims any
run that is measurably louder than the file's own noise floor.
"""
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from audio_synth import SR, build  # noqa: E402
from cutdeck.contracts import CUT, CutConfig  # noqa: E402
from cutdeck.rough_cut import analysis_ingest_kwargs  # noqa: E402
from cutdeck.sequence_mixdown import plan_from_mixdown  # noqa: E402
from transcribe.pipeline import ingest as ingest_mod  # noqa: E402
from transcribe.timebase import Timebase  # noqa: E402

CONFIG = Path(__file__).parent.parent / "transcribe" / "config.yaml"
AGGRESSIVE = Path(__file__).parent.parent / "transcribe" / "config.aggressive_cut.yaml"
WIN = int(0.02 * SR)


def _raw_config(preset: str = "standard") -> dict:
    from cutdeck.rough_cut import _deep_update
    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    if preset == "aggressive":
        _deep_update(raw, yaml.safe_load(AGGRESSIVE.read_text(encoding="utf-8")))
    return raw


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    audio, marks = build()
    path = tmp_path_factory.mktemp("synth") / "synth.wav"
    sf.write(path, audio, SR)
    return str(path), audio, marks


def _db(w):
    return 20 * np.log10(np.sqrt(np.mean(w ** 2) + 1e-9))


def _audible_windows_ms(audio):
    """Start-ms of every 20 ms window louder than the file's noise floor + 15 dB."""
    n = len(audio) // WIN
    dbs = np.array([_db(audio[i * WIN:(i + 1) * WIN]) for i in range(n)])
    floor = max(float(np.percentile(dbs, 5)), -65.0)
    return [i * 20 for i in range(n) if dbs[i] >= floor + 15.0]


def _plan(path, raw, monkeypatch, vad_segments=None):
    if vad_segments is not None:
        monkeypatch.setattr(ingest_mod, "_vad_chunks", lambda *a, **k: vad_segments)
    cfg = CutConfig.from_yaml(raw)
    res = ingest_mod.ingest(path, denoise=False, materialize_chunks=False,
                            **analysis_ingest_kwargs(raw))
    return plan_from_mixdown(path, 0, cfg, timebase=Timebase.from_decimal_fps(30),
                             ingest_result=res)


def _cuts(plan):
    return [(s.src_in_ms, s.src_out_ms) for s in plan.spans if s.action == CUT]


def _cut_ms_inside(cuts, start_ms, end_ms):
    return sum(max(0, min(b, end_ms) - max(a, start_ms)) for a, b in cuts)


def _lost(cuts, audible_ms):
    return [t for t in audible_ms if any(a <= t < b for a, b in cuts)]


def _blind_vad(marks):
    """A VAD that hears the short words but misses the held vowel (the reported failure)."""
    return [(int(marks[k][0] * SR), int(marks[k][1] * SR)) for k in ("word1", "word2")]


@pytest.mark.parametrize("preset", ["standard", "aggressive"])
def test_held_vowel_is_never_cut_when_vad_misses_it(synth, monkeypatch, preset):
    path, audio, marks = synth
    cuts = _cuts(_plan(path, _raw_config(preset), monkeypatch, _blind_vad(marks)))
    a, b = (int(x * 1000) for x in marks["ahhh"])
    held = [t for t in _audible_windows_ms(audio) if a <= t < b]
    assert len(held) > 100, "fixture must contain a long audible vowel"
    assert _lost(cuts, held) == [], f"held vowel cut: {cuts}"
    assert _lost(cuts, _audible_windows_ms(audio)) == []


def test_vad_finding_nothing_still_keeps_all_audible_sound(synth, monkeypatch):
    path, audio, _ = synth
    cuts = _cuts(_plan(path, _raw_config(), monkeypatch, vad_segments=[]))
    assert _lost(cuts, _audible_windows_ms(audio)) == []


@pytest.mark.parametrize("preset", ["standard", "aggressive"])
def test_true_silence_is_still_cut_aggressively(synth, monkeypatch, preset):
    path, _, marks = synth
    cuts = _cuts(_plan(path, _raw_config(preset), monkeypatch, _blind_vad(marks)))
    silence = [(int(marks[k][0] * 1000), int(marks[k][1] * 1000))
               for k in ("sil1", "sil2", "sil3", "sil4")]
    total = sum(b - a for a, b in silence)
    removed = sum(_cut_ms_inside(cuts, a, b) for a, b in silence)
    # 4 silences, each keeps at most the pads plus the fade-out margin on one side
    assert removed >= total - 4 * 400, f"removed {removed} of {total} ms of silence"


def test_real_vad_keeps_held_vowel(synth, monkeypatch):
    pytest.importorskip("torch")
    try:
        ingest_mod._load_silero()
    except Exception:
        pytest.skip("silero VAD unavailable offline")
    path, audio, marks = synth
    cuts = _cuts(_plan(path, _raw_config(), monkeypatch))
    assert _lost(cuts, _audible_windows_ms(audio)) == []


def test_sound_runs_ignore_clicks_and_keep_fading_tails():
    floor = np.random.default_rng(0).standard_normal(SR * 4).astype(np.float32) * 10 ** (-58 / 20)
    click = floor.copy()
    click[SR:SR + 160] += 0.3                       # 10 ms click
    assert ingest_mod.sound_runs(click, SR, margin_db=15, tail_db=6, min_ms=100) == []
    tone = floor.copy()
    t = np.arange(SR) / SR
    tone[SR:2 * SR] += (0.2 * np.sin(2 * np.pi * 150 * t) * np.exp(-3 * t)).astype(np.float32)
    runs = ingest_mod.sound_runs(tone, SR, margin_db=15, tail_db=6, min_ms=100)
    assert len(runs) == 1 and runs[0][0] <= 1020 and runs[0][1] >= 1700
