"""Engine.unload() teardown contract tests (issue #11).

Tests the *contract* of the base ritual (drop handles -> gc.collect() ->
empty_cache()), not the allocator: actual VRAM reclamation needs a real GPU
and isn't assertable on a CPU test runner (see the ticket's Testing
Decisions). A purpose-built Engine subclass reaches `_release()` without a
model, the same fake-backend-into-a-private-handle pattern
test_qwen3_asr.py/test_phase4_typhoon.py use for their adapters.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe.contracts import EngineInput, EngineResult
from transcribe.engines.base import Engine


class _RecordingEngine(Engine):
    """Minimal concrete Engine recording how many times _release() runs."""

    def __init__(self, raise_in_release: bool = False):
        self.release_calls = 0
        self._raise_in_release = raise_in_release

    def load(self) -> None:
        pass

    def transcribe(self, inp: EngineInput) -> EngineResult:
        return EngineResult(tokens=[], engine_name="recording", raw={})

    def _release(self) -> None:
        self.release_calls += 1
        if self._raise_in_release:
            raise RuntimeError("boom")


def test_unload_invokes_release_exactly_once():
    eng = _RecordingEngine()
    eng.unload()
    assert eng.release_calls == 1


def test_unload_before_load_does_not_raise():
    eng = _RecordingEngine()
    eng.unload()  # never loaded — must be harmless
    assert eng.release_calls == 1


def test_unload_twice_is_harmless():
    eng = _RecordingEngine()
    eng.unload()
    eng.unload()  # second call — must not raise
    assert eng.release_calls == 2


def test_release_raising_does_not_prevent_teardown_completing():
    eng = _RecordingEngine(raise_in_release=True)
    eng.unload()  # must not propagate — the rest of the ritual still runs
    assert eng.release_calls == 1


def test_release_raising_is_logged_not_swallowed(caplog):
    import logging

    eng = _RecordingEngine(raise_in_release=True)
    with caplog.at_level(logging.ERROR, logger="transcribe.engines.base"):
        eng.unload()
    assert any("_release() raised" in r.getMessage() for r in caplog.records)


def test_default_release_is_noop():
    """Base's default _release() (used by mock/passthrough) does nothing."""

    class _Plain(Engine):
        def load(self) -> None:
            pass

        def transcribe(self, inp: EngineInput) -> EngineResult:
            return EngineResult(tokens=[], engine_name="plain", raw={})

    plain = _Plain()
    plain.unload()  # no _release() override — must not raise


def test_mock_and_passthrough_load_transcribe_unload_via_registry():
    from transcribe.engines.registry import get_engine

    for name in ("mock", "passthrough"):
        eng = get_engine(name)
        eng.load()
        eng.transcribe(EngineInput(audio_path="fake.wav"))
        eng.unload()
        eng.unload()  # idempotent


def test_unload_survives_torch_being_unimportable(monkeypatch):
    """mock/passthrough must tear down cleanly even where `import torch`
    fails — the ritual wraps that import exactly like typhoon_rt's own
    unload() already did (see base.py's unload() docstring/comment), which
    is what makes "no torch import required" true for these two engines."""
    import builtins

    real_import = builtins.__import__

    def _no_torch(name, *args, **kwargs):
        if name == "torch" or name.startswith("torch."):
            raise ImportError("simulated: torch not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_torch)

    eng = _RecordingEngine()
    eng.unload()  # must not raise ImportError
    assert eng.release_calls == 1


def test_prefers_whole_file_does_not_import_torch(monkeypatch):
    """Pins the lazy-import decision: answering a capability question via the
    registry must not pull torch in, even though unload() itself imports it
    lazily once an engine is actually torn down."""
    import builtins

    real_import = builtins.__import__

    def _guarded_import(name, *args, **kwargs):
        if name == "torch" or name.startswith("torch."):
            raise AssertionError("prefers_whole_file() must not import torch")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)

    # Ensure a clean re-import path isn't required: registry.py + base.py are
    # already imported by the time this test runs, which is exactly the
    # scenario the ticket cares about (asking the capability question later,
    # without ever having imported torch for it).
    from transcribe.engines.registry import prefers_whole_file

    assert prefers_whole_file("mock") is False
