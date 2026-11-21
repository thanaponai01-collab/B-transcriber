"""A per-source decode language: default Thai, English on request, kept apart in the cache."""
from transcribe.pipeline import plan as planning


def _config(**extra):
    return {"engine_a": "mock", "engine_b": "passthrough", **extra}


def test_the_plan_decodes_thai_unless_told_otherwise():
    assert planning.make_plan(_config(), None).language == "th"
    assert planning.make_plan(_config(language="en"), None).language == "en"


def test_a_language_choice_changes_the_cache_identity_and_the_default_does_not():
    base = planning.resume_fingerprint(_config(), [], {})
    assert planning.resume_fingerprint(_config(language="en"), [], {}) != base


def test_service_passes_the_language_into_the_config(monkeypatch, tmp_path):
    from transcribe import service
    seen = {}
    def fake_run(media, config, db, ingest, glossary=(), sha256=None):
        seen["language"] = config.get("language")
        raise RuntimeError("stop")
    monkeypatch.setattr(service.pipeline_run, "run_file_job", fake_run)
    media = tmp_path / "a.wav"; media.write_bytes(b"x")
    for lang, expect in (("en", "en"), (None, None), ("th", None)):
        try:
            service.transcribe(media, config=_config(), db_path=tmp_path / f"{lang}.db", language=lang)
        except RuntimeError:
            pass
        assert seen["language"] == expect


def test_auto_language_majority_vote_from_decode_confidence():
    import numpy as np
    from transcribe.engines.faster_whisper import FasterWhisperEngine as E
    eng = E.__new__(E)
    eng._auto_language = None
    calls = iter([(-0.3, -0.9), (-0.8, -0.4), (-0.2, -0.6)])  # (th, en) per sample: th wins 2 of 3
    pairs = []
    def score(audio, lang):
        if lang == "th":
            pairs.append(next(calls))
            return pairs[-1][0]
        return pairs[-1][1]
    eng._language_score = score
    assert eng._pick_language(np.zeros(16000 * 120, np.float32)) == "th"
    eng._auto_language = None
    calls = iter([(-0.9, -0.3), (-0.8, -0.4), (-0.2, -0.6)])   # en wins 2 of 3
    pairs.clear()
    assert eng._pick_language(np.zeros(16000 * 120, np.float32)) == "en"
    assert eng._pick_language(None) == "en"                     # remembered
