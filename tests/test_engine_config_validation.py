"""Engine settings must not be discarded on constructor errors."""
from pathlib import Path

import pytest
import yaml

from transcribe.engines import registry
from transcribe.pipeline.engine_run import build_engine


@pytest.mark.parametrize('entry', ['pipeline', 'registry'])
def test_unknown_setting_fails_before_constructor_runs(monkeypatch, entry):
    calls = []

    class StrictEngine:
        def __init__(self, device='cpu', beam_size=5):
            calls.append(beam_size)

    monkeypatch.setitem(registry._REGISTRY, 'strict_test', StrictEngine)
    with pytest.raises(TypeError, match='strict_test.*beam_szie'):
        if entry == 'pipeline':
            build_engine('strict_test', 'cpu', {
                'engines': {'strict_test': {'beam_szie': 3}}})
        else:
            registry.get_engine('strict_test', device='cpu', beam_szie=3)
    assert calls == []


def test_internal_type_error_propagates_without_retrying_defaults(monkeypatch):
    calls = []
    error = TypeError('decoder initialization failed')

    class BrokenEngine:
        def __init__(self, device='cpu', beam_size=5):
            calls.append(beam_size)
            if beam_size != 5:
                raise error

    monkeypatch.setitem(registry._REGISTRY, 'broken_test', BrokenEngine)
    with pytest.raises(TypeError) as raised:
        build_engine('broken_test', 'cpu', {'engines': {'broken_test': {'beam_size': 3}}})
    assert raised.value is error
    assert calls == [3]


def test_missing_required_setting_has_engine_context(monkeypatch):
    class RequiredEngine:
        def __init__(self, device, model_id):
            pytest.fail('invalid settings must not reach the constructor')

    monkeypatch.setitem(registry._REGISTRY, 'required_test', RequiredEngine)
    with pytest.raises(TypeError, match='required_test.*model_id'):
        build_engine('required_test', 'cpu', {})


def test_variadic_engine_constructor_keeps_supported_overrides(monkeypatch):
    seen = []

    class FlexibleEngine:
        def __init__(self, device='cpu', **kwargs):
            seen.append((device, kwargs))

    monkeypatch.setitem(registry._REGISTRY, 'flexible_test', FlexibleEngine)
    build_engine('flexible_test', 'cuda', {'engines': {'flexible_test': {'beam_size': 3}}})
    assert seen == [('cuda', {'beam_size': 3})]


def test_valid_settings_reach_constructor_once(monkeypatch):
    calls = []

    class StrictEngine:
        def __init__(self, device='cpu', *, beam_size=5):
            calls.append((device, beam_size))

    monkeypatch.setitem(registry._REGISTRY, 'strict_test', StrictEngine)
    build_engine('strict_test', 'cuda', {'engines': {'strict_test': {'beam_size': 3}}})
    assert calls == [('cuda', 3)]


def test_unknown_engine_still_raises_key_error():
    with pytest.raises(KeyError, match='Unknown engine'):
        build_engine('does_not_exist', 'cpu', {})


def test_production_config_constructs_active_engines_without_loading_models():
    config = yaml.safe_load((Path(__file__).parents[1] / 'transcribe/config.yaml').read_text(encoding='utf-8'))
    engine = build_engine(config['engine_a'], 'cpu', config)
    assert engine._beam_size == config['engines']['faster_whisper']['beam_size']
    assert engine._recover_short_spans is True
    assert build_engine(config['engine_b'], 'cpu', config) is not None
