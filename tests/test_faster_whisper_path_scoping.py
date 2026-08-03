"""faster_whisper's CUDA-DLL PATH mutation must be load()-scoped, not
process-lifetime.

Why this exists: `_register_cuda_dll_dirs()` prepends nvidia pip wheels' bin
dirs (incl. a CUDA-12 cudnn64_9.dll) onto os.environ["PATH"] so CTranslate2's
bare LoadLibrary calls can find cublas64_12.dll. That mutation used to persist
for the rest of the process. Reproduced 2026-07-16: loading typhoon_rt (NeMo,
torch 2.13+cu130) in the SAME process afterward crashed on its very first conv
forward pass with CUDNN_STATUS_SUBLIBRARY_VERSION_MISMATCH — confirmed via a
standalone repro that calling only `_register_cuda_dll_dirs()` (no CTranslate2
model ever loaded) was sufficient to break NeMo's cuDNN resolution. Any
same-process Engine B built on a different CUDA-toolkit generation than
CTranslate2's bundled one is exposed to this. The fix restores PATH in
FasterWhisperEngine.unload().

Run: python -m pytest tests/test_faster_whisper_path_scoping.py -v
"""

import os

from transcribe.engines.faster_whisper import _register_cuda_dll_dirs


def test_register_cuda_dll_dirs_returns_pre_mutation_path(monkeypatch):
    monkeypatch.setenv("PATH", r"C:\some\original\path")
    original = os.environ["PATH"]
    returned = _register_cuda_dll_dirs()
    assert returned == original


def test_unload_restores_path_to_pre_load_value(monkeypatch):
    from transcribe.engines.faster_whisper import FasterWhisperEngine

    monkeypatch.setenv("PATH", r"C:\some\original\path")
    original = os.environ["PATH"]

    eng = FasterWhisperEngine.__new__(FasterWhisperEngine)  # skip __init__'s ctor work
    eng._pipeline = None
    eng._model = None
    eng._pre_load_path = _register_cuda_dll_dirs()  # simulates what load() does

    # The mutation must actually have changed PATH for this test to prove anything
    # (a no-op environment, e.g. no nvidia site-packages dir, would trivially pass).
    mutated = os.environ["PATH"]

    eng.unload()

    assert os.environ["PATH"] == original
    if mutated != original:
        assert os.environ["PATH"] != mutated


def test_unload_is_idempotent_on_path_restore(monkeypatch):
    from transcribe.engines.faster_whisper import FasterWhisperEngine

    monkeypatch.setenv("PATH", r"C:\some\original\path")
    original = os.environ["PATH"]

    eng = FasterWhisperEngine.__new__(FasterWhisperEngine)
    eng._pipeline = None
    eng._model = None
    eng._pre_load_path = _register_cuda_dll_dirs()

    eng.unload()
    eng.unload()  # must not raise or further mutate PATH
    assert os.environ["PATH"] == original
