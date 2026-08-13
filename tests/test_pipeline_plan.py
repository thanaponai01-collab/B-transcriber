"""transcribe/pipeline/plan.py — the pipeline's decisions, addressed directly.

These construct a config dict and a resume phase, call the function, and assert
on the returned plan. No audio, no database, no GPU, no engine instantiation —
which is the point of the seam. The resume phase matrix in particular is a
parametrized table covering every phase value including None, so coverage of the
matrix is visible rather than sampled.

Run: python -m pytest tests/test_pipeline_plan.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import transcribe.engines.mock  # noqa: F401 — registers "mock" (prefers_whole_file=False)
from transcribe.engines.base import Engine
from transcribe.engines.registry import register
from transcribe.pipeline import plan as planning


@register("plan_test_whole_file")
class _WholeFileTestEngine(Engine):
    prefers_whole_file = True

    def load(self): ...
    def transcribe(self, inp): ...
    def unload(self): ...


WHOLE = "plan_test_whole_file"
CHUNK = "mock"


def _cfg(**kw):
    base = {"engine_a": WHOLE, "engine_b": "passthrough"}
    base.update(kw)
    return base


# ── the resume phase matrix ─────────────────────────────────────────────────
# A resumed 'failed' job skips every phase up to and including its last recorded
# one. Every phase value, including None (a fresh job), in one table.

@pytest.mark.parametrize("phase,skip_a,skip_b", [
    (None,                          False, False),
    ("ingested",                    False, False),
    (planning.PHASE_ENGINE_A_DONE,  True,  False),
    (planning.PHASE_ENGINE_B_DONE,  True,  True),
    (planning.PHASE_RECONCILED,     True,  True),
    (planning.PHASE_WRITTEN,        True,  True),
])
def test_resume_phase_decides_which_engines_are_skipped(phase, skip_a, skip_b):
    p = planning.make_plan(_cfg(), phase)
    assert p.skip_engine_a is skip_a
    assert p.skip_engine_b is skip_b


def test_an_unknown_phase_string_skips_nothing():
    """Fail safe: an unrecognised phase re-runs everything rather than silently
    skipping GPU work whose result was never cached."""
    p = planning.make_plan(_cfg(), "something_a_future_version_wrote")
    assert p.skip_engine_a is False and p.skip_engine_b is False


# ── canonical engine names ──────────────────────────────────────────────────

def test_engine_b_is_config_engine_b_when_self_ensemble_is_off():
    assert planning.canonical_engine_names(_cfg(engine_b="mock")) == (WHOLE, "mock")


def test_engine_b_is_canonicalised_when_self_ensemble_is_on():
    """Job identity must say self_ensemble regardless of config's raw engine_b
    string — otherwise a config-only activation mislabels engine_result rows and
    can cross-resume into a genuine passthrough job's cached results."""
    cfg = _cfg(engine_b="passthrough", self_ensemble={"enabled": True})
    assert planning.canonical_engine_names(cfg) == (WHOLE, planning.SELF_ENSEMBLE)
    assert planning.make_plan(cfg, None).engine_b_name == planning.SELF_ENSEMBLE


def test_make_plan_and_canonical_engine_names_cannot_disagree():
    """run_file calls one before the job lookup and the other after; they are the
    same derivation, and this is the assertion that keeps it that way."""
    for cfg in (_cfg(), _cfg(engine_b="mock"),
                _cfg(self_ensemble={"enabled": True}),
                _cfg(engine_b="mock", self_ensemble={"enabled": False})):
        p = planning.make_plan(cfg, None)
        assert (p.engine_a_name, p.engine_b_name) == planning.canonical_engine_names(cfg)


# ── self-ensemble validity, as a pure predicate ─────────────────────────────

def test_self_ensemble_requires_a_whole_file_engine_a():
    """No engine is constructed to answer this — the capability is read off the
    registered class."""
    with pytest.raises(ValueError, match="self_ensemble.enabled requires a whole-file"):
        planning.make_plan(_cfg(engine_a=CHUNK, self_ensemble={"enabled": True}), None)


def test_self_ensemble_with_a_whole_file_engine_a_is_accepted():
    p = planning.make_plan(_cfg(self_ensemble={"enabled": True}), None)
    assert p.self_ensemble_enabled is True


def test_a_chunk_engine_a_is_fine_when_self_ensemble_is_off():
    p = planning.make_plan(_cfg(engine_a=CHUNK), None)
    assert p.self_ensemble_enabled is False


# ── decode parameters ───────────────────────────────────────────────────────

def test_decode_overrides_are_none_when_self_ensemble_is_off():
    """None everywhere preserves each engine's own production defaults — a
    temperature of 0.0 is NOT the same as not passing one."""
    p = planning.make_plan(_cfg(), None)
    assert (p.temperature_a, p.beam_size_a, p.temperature_b, p.beam_size_b) == (None,) * 4


def test_self_ensemble_decode_defaults():
    p = planning.make_plan(_cfg(self_ensemble={"enabled": True}), None)
    assert p.temperature_a == 0.0
    assert p.beam_size_a is None       # no override -> engine's own beam width
    assert p.temperature_b == 0.2
    assert p.beam_size_b == 1          # sampling mode; temperature alone is a no-op at beam>1


def test_self_ensemble_decode_overrides_are_read_from_config():
    p = planning.make_plan(_cfg(self_ensemble={
        "enabled": True, "temperature_a": 0.1, "beam_size_a": 3,
        "temperature_b": 0.7, "beam_size_b": 2}), None)
    assert (p.temperature_a, p.beam_size_a, p.temperature_b, p.beam_size_b) == (0.1, 3, 0.7, 2)


# ── capability-derived flags ────────────────────────────────────────────────

def test_two_whole_file_engines_need_full_audio_and_no_chunks():
    p = planning.make_plan(_cfg(engine_a=WHOLE, engine_b=WHOLE), None)
    assert p.needs_full_audio is True
    assert p.chunk_engine_active is False


def test_a_chunk_engine_anywhere_makes_it_a_chunk_run():
    assert planning.make_plan(_cfg(engine_a=CHUNK), None).chunk_engine_active is True
    assert planning.make_plan(_cfg(engine_b=CHUNK), None).chunk_engine_active is True


def test_passthrough_is_never_a_chunk_engine():
    """passthrough consumes nothing, so it must not force ingest to cut chunks."""
    p = planning.make_plan(_cfg(engine_a=WHOLE, engine_b="passthrough"), None)
    assert p.chunk_engine_active is False


def test_self_ensemble_ignores_config_engine_b_for_capability_questions():
    """Under self-ensemble there is no second engine, so config's raw engine_b
    must not drag ingest into chunk mode or be looked up in the registry at all."""
    p = planning.make_plan(
        _cfg(engine_b="a_name_that_is_not_registered", self_ensemble={"enabled": True}), None)
    assert p.chunk_engine_active is False
    assert p.needs_full_audio is True


# ── batch / overlap settings ────────────────────────────────────────────────

def test_batch_and_overlap_defaults_and_overrides():
    p = planning.make_plan(_cfg(), None)
    assert p.engine_batch_size == 8 and p.chunk_overlap_ms == 750
    p = planning.make_plan(_cfg(engine_batch_size=4, chunk_overlap_ms=250), None)
    assert p.engine_batch_size == 4 and p.chunk_overlap_ms == 250


def test_the_plan_is_a_value_that_can_be_logged():
    """A maintainer debugging a resumed job should be able to see what the
    pipeline decided rather than infer it from behaviour."""
    text = str(planning.make_plan(_cfg(self_ensemble={"enabled": True}), "engine_a_done"))
    assert "skip_engine_a=True" in text
    assert "self_ensemble_enabled=True" in text
