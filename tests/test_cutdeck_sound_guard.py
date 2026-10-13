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


def test_aggressive_cut_handles_40ms_pre_60ms_post_and_120ms_threshold(monkeypatch):
    """Aggressive cuts leave 40ms pre / 60ms post and cut every silence >= 120ms."""
    cfg = _raw_config("aggressive")
    assert cfg["cut"]["pad_pre_ms"] == 40
    assert cfg["cut"]["pad_post_ms"] == 60
    assert cfg["cut"]["min_silence_ms"] == 119

    # Test with synthetic speech segments having silences of 110ms, 120ms, and 300ms
    # Speech 1: 0 - 1000ms
    # Silence 1: 1000 - 1110ms (110ms: < 120ms -> kept, NOT cut)
    # Speech 2: 1110 - 2000ms
    # Silence 2: 2000 - 2120ms (120ms: >= 120ms -> cut from 2060 to 2080, exactly 20ms)
    # Speech 3: 2120 - 3000ms
    # Silence 3: 3000 - 3300ms (300ms: >= 120ms -> cut from 3060 to 3260, exactly 200ms)
    # Speech 4: 3300 - 4000ms
    from cutdeck.contracts import CutConfig
    from cutdeck.rules import build_cut_spans
    from transcribe.pipeline.ingest import SpeechSpan
    spans = [
        SpeechSpan(0, 0, 1000, "speech"),
        SpeechSpan(1, 1000, 1110, "silence"),
        SpeechSpan(2, 1110, 2000, "speech"),
        SpeechSpan(3, 2000, 2120, "silence"),
        SpeechSpan(4, 2120, 3000, "speech"),
        SpeechSpan(5, 3000, 3300, "silence"),
        SpeechSpan(6, 3300, 4000, "speech"),
    ]
    cut_cfg = CutConfig.from_yaml(cfg)
    plan_spans = build_cut_spans(tokens=[], spans=spans, duration_ms=4000, cfg=cut_cfg)
    cuts = [(s.src_in_ms, s.src_out_ms) for s in plan_spans if s.action == CUT]

    # Silence 1 (110ms) must NOT have any cut inside it
    assert not any(1000 <= a and b <= 1110 for a, b in cuts)
    # Silence 2 (120ms) must be cut from 2060 (1000+60 post) to 2080 (2120-40 pre)
    assert (2060, 2080) in cuts
    # Silence 3 (300ms) must be cut from 3060 to 3260
    assert (3060, 3260) in cuts


def test_aggressive_breath_and_sfx_preserved_without_vad(tmp_path, monkeypatch):
    """Soft breath (+12 dB above noise floor) and music/SFX are preserved even if VAD hears nothing."""
    rng = np.random.default_rng(42)
    # 4 seconds: 1s silence, 0.2s breath (+12 dB), 1s silence, 0.5s SFX/chime, 1.3s silence
    floor = rng.standard_normal(SR * 4).astype(np.float32) * 10 ** (-55 / 20)
    audio = floor.copy()

    # Breath: shaped pink/filtered noise from 1.0s to 1.2s at -43 dB (+12 dB above floor)
    t_breath = np.arange(int(0.2 * SR))
    breath_noise = rng.standard_normal(len(t_breath)).astype(np.float32) * 10 ** (-43 / 20)
    # simple envelope
    env = np.sin(np.pi * np.linspace(0, 1, len(t_breath)))
    audio[SR:SR + len(t_breath)] += breath_noise * env

    # SFX: 0.5s chime / tone from 2.2s to 2.7s
    t_sfx = np.arange(int(0.5 * SR)) / SR
    sfx = (0.1 * np.sin(2 * np.pi * 440 * t_sfx)).astype(np.float32)
    audio[int(2.2 * SR):int(2.2 * SR) + len(t_sfx)] += sfx

    path = tmp_path / "breath_sfx.wav"
    sf.write(path, audio, SR)

    # VAD is completely blind (0 speech found)
    cuts = _cuts(_plan(str(path), _raw_config("aggressive"), monkeypatch, vad_segments=[]))

    # Calculate audible windows for the breath and SFX
    # Breath window: 1000 - 1200ms
    # SFX window: 2200 - 2700ms
    breath_lost = [t for t in range(1040, 1160, 20) if any(a <= t < b for a, b in cuts)]
    assert breath_lost == [], f"Breath was cut: {cuts}"

    sfx_lost = [t for t in range(2240, 2660, 20) if any(a <= t < b for a, b in cuts)]
    assert sfx_lost == [], f"SFX was cut: {cuts}"
