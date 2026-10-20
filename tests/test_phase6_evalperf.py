"""Phase 6 acceptance — eval perf + hygiene (rapidfuzz, align linearization).

Run: python -m pytest tests/test_phase6_evalperf.py -v
"""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe.contracts import RecognizedToken
from transcribe.pipeline import align_hyp


# ── 6.1 rapidfuzz edit distance matches the pure-Python fallback ──────────────

def test_edit_distance_matches_pure_python():
    from transcribe.eval.metrics import _edit_distance, _edit_distance_py
    cases = [
        ("kitten", "sitting"),
        ("", "abc"),
        ("สวัสดีครับ", "สวัสดีคระ"),
        (["a", "b", "c"], ["a", "x", "c"]),
    ]
    for ref, hyp in cases:
        assert _edit_distance(ref, hyp) == _edit_distance_py(ref, hyp)


# ── 6.3 windowed align == brute-force align on random token sets ──────────────

def _brute_align(tokens_a, tokens_b):
    """Reference implementation: the pre-linearization O(A×B) full scan."""
    from transcribe.pipeline.align_hyp import _token_overlap_ms, _score, AlignSlot, _MATCH_PROX_MS
    if not tokens_a and not tokens_b:
        return []
    matched_b = set()
    pairs = []
    for ta in tokens_a:
        best_j, best_score = -1, -1.0
        for j, tb in enumerate(tokens_b):
            if j in matched_b:
                continue
            if _token_overlap_ms(ta, tb) == 0 and abs(ta.start_ms - tb.start_ms) > _MATCH_PROX_MS:
                continue
            s = _score(ta, tb)
            if s > best_score:
                best_score, best_j = s, j
        if best_j >= 0 and best_score > 0.1:
            matched_b.add(best_j)
            pairs.append((ta, tokens_b[best_j]))
        else:
            pairs.append((ta, None))
    for j, tb in enumerate(tokens_b):
        if j not in matched_b:
            pairs.append((None, tb))
    slots = [AlignSlot([ta] if ta else [], [tb] if tb else []) for ta, tb in pairs]
    slots.sort(key=lambda s: min((t.start_ms for t in s.candidates_a + s.candidates_b), default=0))
    return slots


def _rand_tokens(n, rng):
    vocab = ["โอเค", "ครับ", "hello", "world", "นะ", "AI", "test"]
    toks = []
    t = 0
    for _ in range(n):
        t += rng.randint(0, 800)
        dur = rng.randint(200, 6000)  # realistic ASR cue durations
        toks.append(RecognizedToken(rng.choice(vocab), t, t + dur, 0.9, "thai"))
        t += dur
    return toks


def _key(slots):
    return [
        ([(t.text, t.start_ms) for t in s.candidates_a],
         [(t.text, t.start_ms) for t in s.candidates_b])
        for s in slots
    ]


def test_windowed_align_equals_bruteforce():
    rng = random.Random(1234)
    for _ in range(200):
        a = _rand_tokens(rng.randint(0, 12), rng)
        b = _rand_tokens(rng.randint(0, 12), rng)
        assert _key(align_hyp.align(a, b)) == _key(_brute_align(a, b))


# ── 6.4 harness keeps Engine A warm across clips & avoids duplicate decode/hash ──

def _synth_wav(dirpath: Path, stem: str, seconds: float = 0.5):
    import numpy as np
    import soundfile as sf
    t = np.linspace(0, seconds, int(16000 * seconds), endpoint=False)
    p = dirpath / f"{stem}.wav"
    sf.write(p, (0.2 * np.sin(2 * np.pi * 200 * t)).astype(np.float32), 16000)
    return p


def test_harness_passthrough_keeps_engine_a_warm_and_decodes_and_hashes_once_per_clip(monkeypatch, tmp_path):
    """Across a multi-clip run_harness invocation with engine_b='passthrough':
    - Engine A's load() and unload() are each called once (not once per clip),
      and unload() still fires in finally even if a clip raises.
    - ingest.load_audio is called once per clip (not twice), and RTF is still
      computed from the stored media duration_ms.
    - store.sha256_of_file is called once per clip (not twice).
    """
    from transcribe.db import store
    from transcribe.engines.mock import MockEngine
    from transcribe.eval import harness
    from transcribe.pipeline import ingest

    monkeypatch.setattr(ingest, "_load_silero",
                        lambda: (object(), lambda a, m, **k: [{"start": 0, "end": len(a)}]))

    clip1 = _synth_wav(tmp_path, "clip1", seconds=0.5)
    clip2 = _synth_wav(tmp_path, "clip2", seconds=1.0)
    ref = [{"text": "สวัสดี", "script": "thai", "start_ms": 0, "end_ms": 500}]
    monkeypatch.setattr(harness, "_load_goldenset", lambda: [(clip1, ref), (clip2, ref)])

    events = []
    orig_load = MockEngine.load
    orig_unload = MockEngine.unload

    def spy_load(self):
        events.append(("load", id(self)))
        return orig_load(self)

    def spy_unload(self):
        events.append(("unload", id(self)))
        return orig_unload(self)

    monkeypatch.setattr(MockEngine, "load", spy_load)
    monkeypatch.setattr(MockEngine, "unload", spy_unload)

    audio_loads = []
    orig_load_audio = ingest.load_audio

    def spy_load_audio(path):
        audio_loads.append(str(path))
        return orig_load_audio(path)

    monkeypatch.setattr(ingest, "load_audio", spy_load_audio)

    hash_calls = []
    orig_sha256 = store.sha256_of_file

    def spy_sha256(path):
        hash_calls.append(str(path))
        return orig_sha256(path)

    monkeypatch.setattr(store, "sha256_of_file", spy_sha256)

    db = tmp_path / "eval.db"
    cfg = {
        "engine_a": "mock",
        "engine_b": "passthrough",
        "denoise": False,
        "drop_tokens_over_silence": False,
        "regression_tolerance": 0.02,
    }
    res = harness.run_harness(cfg, db, pipeline_fn=None)
    assert res is not None and res.passed
    assert res.rtf is not None and res.rtf > 0.0

    loads = [e for e in events if e[0] == "load"]
    unloads = [e for e in events if e[0] == "unload"]
    assert len(loads) == 1, f"Expected 1 Engine A load across 2 clips, got {len(loads)}: {events}"
    assert len(unloads) == 1, f"Expected 1 Engine A unload across 2 clips, got {len(unloads)}: {events}"
    assert loads[0][1] == unloads[0][1]
    assert len(audio_loads) == 2, f"Expected 1 load_audio per clip (2 total), got {len(audio_loads)}: {audio_loads}"
    assert len(hash_calls) == 2, f"Expected 1 sha256_of_file per clip (2 total), got {len(hash_calls)}: {hash_calls}"


def test_harness_warm_engine_a_unloads_on_clip_failure(monkeypatch, tmp_path):
    """If a clip fails midway through run_harness, the warm Engine A is unloaded in finally."""
    import pytest
    from transcribe.engines.mock import MockEngine
    from transcribe.eval import harness
    from transcribe.pipeline import ingest

    monkeypatch.setattr(ingest, "_load_silero",
                        lambda: (object(), lambda a, m, **k: [{"start": 0, "end": len(a)}]))

    clip1 = _synth_wav(tmp_path, "clip1", seconds=0.5)
    clip2 = _synth_wav(tmp_path, "clip2", seconds=0.5)
    ref = [{"text": "สวัสดี", "script": "thai", "start_ms": 0, "end_ms": 500}]
    monkeypatch.setattr(harness, "_load_goldenset", lambda: [(clip1, ref), (clip2, ref)])

    events = []
    orig_load = MockEngine.load
    orig_unload = MockEngine.unload
    orig_transcribe = MockEngine.transcribe
    call_count = 0

    def spy_load(self):
        events.append(("load", id(self)))
        return orig_load(self)

    def spy_unload(self):
        events.append(("unload", id(self)))
        return orig_unload(self)

    def failing_transcribe(self, inp):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("boom on second clip")
        return orig_transcribe(self, inp)

    monkeypatch.setattr(MockEngine, "load", spy_load)
    monkeypatch.setattr(MockEngine, "unload", spy_unload)
    monkeypatch.setattr(MockEngine, "transcribe", failing_transcribe)

    db = tmp_path / "eval_fail.db"
    cfg = {
        "engine_a": "mock",
        "engine_b": "passthrough",
        "denoise": False,
        "drop_tokens_over_silence": False,
    }
    with pytest.raises(RuntimeError, match="boom on second clip"):
        harness.run_harness(cfg, db, pipeline_fn=None)

    loads = [e for e in events if e[0] == "load"]
    unloads = [e for e in events if e[0] == "unload"]
    assert len(loads) == 1
    assert len(unloads) == 1
    assert loads[0][1] == unloads[0][1]
