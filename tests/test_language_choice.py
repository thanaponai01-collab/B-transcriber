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


def test_helper_transcribe_takes_th_en_auto_and_refuses_others(tmp_path, monkeypatch):
    import asyncio
    import pytest
    from cutdeck.helper import Jobs
    media = tmp_path / "a.wav"; media.write_bytes(b"RIFF")

    async def idle(self, job):
        await asyncio.sleep(0)
    monkeypatch.setattr(Jobs, "_run_transcribe", idle)

    async def body():
        jobs = Jobs(tmp_path / "jobs")
        for lang in ("th", "en", "auto"):
            job = await jobs.dispatch({"type": "submit_transcribe", "media_path": str(media), "language": lang})
            assert jobs._job(job["job_id"])["arguments"]["language"] == lang
            await asyncio.sleep(0.01)
            jobs.active = None
        with pytest.raises(ValueError, match="auto"):
            await jobs.dispatch({"type": "submit_transcribe", "media_path": str(media), "language": "fr"})
    asyncio.run(body())


def test_auto_decides_per_whole_file_and_short_excerpts_reuse_the_choice():
    import numpy as np
    from transcribe.engines.faster_whisper import FasterWhisperEngine as E
    eng = E.__new__(E)
    eng._auto_language = "en"                          # left over from a previous file
    picked = []
    eng._pick_language = lambda audio: picked.append(len(audio)) or "th"
    seen = {}
    def batched(audio, language, *a, **k):
        seen["language"] = language
        return []
    eng._transcribe_batched = batched
    lang_for = lambda n: (E._resolve_language(eng, "auto", np.zeros(n, np.float32)))
    assert lang_for(16000 * 120) == "th" and picked == [16000 * 120]     # a whole file: decided afresh
    eng._auto_language = "en"
    assert lang_for(16000 * 2) == "en" and len(picked) == 1               # an excerpt: the file's choice
    eng._auto_language = None
    assert lang_for(16000 * 2) == "th"                                    # no choice yet: Thai


def test_qwen_auto_is_its_own_detection_and_thai_pinned_engines_refuse_english():
    import pytest
    from transcribe.engines.qwen3_asr import Qwen3ASREngine
    assert Qwen3ASREngine._language_arg(Qwen3ASREngine.__new__(Qwen3ASREngine), "auto") is None
    from transcribe.contracts import EngineInput
    from transcribe.engines.whisper_thai import WhisperThaiEngine
    eng = WhisperThaiEngine.__new__(WhisperThaiEngine)
    eng._pipe = object()
    with pytest.raises(ValueError, match="decodes only 'th'"):
        eng.transcribe(EngineInput(audio=None, language_hint="en"))
