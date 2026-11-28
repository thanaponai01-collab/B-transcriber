from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

from transcribe.engines.base import Engine

if TYPE_CHECKING:
    pass

_REGISTRY: dict[str, type[Engine]] = {}


def register(name: str):
    def decorator(cls: type[Engine]) -> type[Engine]:
        _REGISTRY[name] = cls
        return cls
    return decorator


def get_engine(name: str, **kwargs) -> Engine:
    """Validate constructor arguments, then instantiate exactly once.

    Binding errors identify the engine and invalid setting. Constructor errors
    propagate unchanged.
    Constructors that explicitly accept **kwargs retain that capability.
    """
    if name not in _REGISTRY:
        _lazy_load(name)
    cls = _REGISTRY[name]
    try:
        inspect.signature(cls).bind(**kwargs)
    except TypeError as error:
        raise TypeError(f"Invalid configuration for engine {name!r}: {error}") from error
    return cls(**kwargs)


def _lazy_load(name: str) -> None:
    loaders = {
        "mock":          "transcribe.engines.mock",
        "whisper_thai":  "transcribe.engines.whisper_thai",
        "faster_whisper": "transcribe.engines.faster_whisper",
        "whisper_multi": "transcribe.engines.whisper_multi",
        "qwen3_asr":     "transcribe.engines.qwen3_asr",
        "passthrough":   "transcribe.engines.null_engine",
    }
    if name not in loaders:
        raise KeyError(f"Unknown engine: {name!r}. Available: {list(loaders)}")
    import importlib
    importlib.import_module(loaders[name])


def prefers_whole_file(name: str) -> bool:
    """Whether an engine is whole-file — answered WITHOUT instantiating it."""
    if name not in _REGISTRY:
        _lazy_load(name)
    return bool(getattr(_REGISTRY[name], "prefers_whole_file", False))

