"""Engine registry — maps name strings to adapter classes.

Config drives engine selection; no component imports a concrete engine directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from transcribe.engines.base import Engine

if TYPE_CHECKING:
    pass

_REGISTRY: dict[str, type[Engine]] = {}


def register(name: str):
    """Decorator that registers an Engine subclass under a name."""
    def decorator(cls: type[Engine]) -> type[Engine]:
        _REGISTRY[name] = cls
        return cls
    return decorator


def get_engine(name: str, **kwargs) -> Engine:
    """Instantiate an engine by registry name. Raises KeyError if unknown."""
    if name not in _REGISTRY:
        _lazy_load(name)
    cls = _REGISTRY[name]
    return cls(**kwargs)


def _lazy_load(name: str) -> None:
    """Import adapter modules on first use so heavy deps load only when needed."""
    loaders = {
        "mock":          "transcribe.engines.mock",
        "whisper_thai":  "transcribe.engines.whisper_thai",
        "whisper_multi": "transcribe.engines.whisper_multi",
        "funasr":        "transcribe.engines.funasr",
        "passthrough":   "transcribe.engines.null_engine",
    }
    if name not in loaders:
        raise KeyError(f"Unknown engine: {name!r}. Available: {list(loaders)}")
    import importlib
    importlib.import_module(loaders[name])


def list_engines() -> list[str]:
    return list(_REGISTRY.keys())
