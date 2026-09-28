"""Engine.unload() order: _release() -> gc.collect() -> torch.cuda.empty_cache().

empty_cache() only frees blocks whose tensors are already collected, so the order is the point
(engines/base.py docstring). Fakes stand in for gc and torch; no GPU needed.
"""
import sys
import types

from transcribe.contracts import EngineInput, EngineResult
from transcribe.engines.base import Engine


def _engine(events, raise_in_release=False):
    class _E(Engine):
        def load(self): pass
        def transcribe(self, inp: EngineInput) -> EngineResult:
            return EngineResult(tokens=[], engine_name="e", raw={})
        def _release(self):
            events.append("release")
            if raise_in_release:
                raise RuntimeError("boom")
    return _E()


def _fake_torch(events, cuda=True):
    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(
        is_available=lambda: cuda, empty_cache=lambda: events.append("empty_cache"))
    return torch


def _run(monkeypatch, events, **kw):
    import transcribe.engines.base as base
    monkeypatch.setattr(base.gc, "collect", lambda *a: events.append("gc"))
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(events, kw.pop("cuda", True)))
    _engine(events, **kw).unload()


def test_release_then_gc_then_empty_cache(monkeypatch):
    events = []
    _run(monkeypatch, events)
    assert events == ["release", "gc", "empty_cache"]


def test_teardown_continues_when_release_raises(monkeypatch):
    events = []
    _run(monkeypatch, events, raise_in_release=True)
    assert events == ["release", "gc", "empty_cache"]


def test_no_cuda_skips_empty_cache_but_still_collects(monkeypatch):
    events = []
    _run(monkeypatch, events, cuda=False)
    assert events == ["release", "gc"]


def test_torch_missing_is_harmless(monkeypatch):
    import transcribe.engines.base as base
    events = []
    monkeypatch.setattr(base.gc, "collect", lambda *a: events.append("gc"))
    monkeypatch.setitem(sys.modules, "torch", None)  # import torch -> ImportError
    _engine(events).unload()
    assert events == ["release", "gc"]
