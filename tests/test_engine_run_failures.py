"""Failure paths must preserve cleanup and explicit engine settings."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from transcribe.pipeline import engine_run as er


@pytest.mark.parametrize("phase", ["a", "b", "resume"])
@pytest.mark.parametrize("failure", ["load", "decode"])
def test_failed_residency_always_unloads(monkeypatch, phase, failure):
    engine = Mock()
    error = RuntimeError("injected failure")
    if failure == "load":
        engine.load.side_effect = error
    monkeypatch.setattr(er, "build_engine", lambda *a: engine)
    monkeypatch.setattr(er, "_log_vram", lambda *a: None)
    monkeypatch.setattr(er, "_transcribe_with", Mock(side_effect=error))
    monkeypatch.setattr(er, "_decode_self_ensemble_b", Mock(side_effect=error))
    save = Mock()
    monkeypatch.setattr(er.store, "save_engine_result", save)
    monkeypatch.setattr(er.store, "get_engine_result",
                        lambda *a: SimpleNamespace(tokens_json="[]", timestamps_final=True))
    plan = SimpleNamespace(skip_engine_a=phase == "resume", skip_engine_b=False,
                           self_ensemble_enabled=phase == "resume",
                           engine_a_name="fake", engine_b_name="fake",
                           engine_batch_size=8, chunk_overlap_ms=750,
                           temperature_a=None, beam_size_a=None)
    inputs = er.DecodeInputs([], None, [], {})
    with pytest.raises(RuntimeError, match="injected failure"):
        if phase == "b":
            er._run_engine_b(None, 1, plan, inputs, "cpu", {}, True, None, None)
        else:
            er._run_engine_a(None, 1, plan, inputs, "cpu", {})
    engine.unload.assert_called_once_with()
    save.assert_not_called()


def test_unknown_setting_is_rejected():
    with pytest.raises(TypeError, match="beam_szie"):
        er.build_engine("faster_whisper", "cpu",
                        {"engines": {"faster_whisper": {"beam_szie": 1}}})


def test_constructor_type_error_is_not_retried(monkeypatch):
    factory = Mock(side_effect=TypeError("internal constructor failure"))
    monkeypatch.setattr(er, "get_engine", factory)
    with pytest.raises(TypeError, match="internal constructor failure"):
        er.build_engine("mock", "cpu", {})
    factory.assert_called_once_with("mock", device="cpu")


def test_valid_overrides_are_preserved():
    engine = er.build_engine("faster_whisper", "cpu",
                            {"engines": {"faster_whisper": {"beam_size": 1, "batch_size": 2}}})
    assert engine._beam_size == 1
    assert engine._batch_size == 2
