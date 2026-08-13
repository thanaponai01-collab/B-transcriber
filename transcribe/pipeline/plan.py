"""Pipeline planning — every decision `run_file` makes before it touches a GPU.

Internal to `transcribe/pipeline/`. Not part of any public interface; deliberately
absent from `pipeline/__init__.py`'s exports.

The decisions behind `run_file` were always pure — functions of the config dict
and one resume row — but the only route to them was a 383-line body, so testing
"does a resumed job at phase X skip engine A?" meant a temp WAV, a real SQLite
file and a registered mock engine. This module is that route.

Nothing here does I/O, instantiates an engine, or loads a model. Engine
capabilities are read off the registered *class* (`registry.prefers_whole_file`),
which is what makes the plan computable before anything is constructed.
"""

from __future__ import annotations

from dataclasses import dataclass

from transcribe.engines import registry

# job_phase values (4.1, GAP-8): a resumed 'failed' job skips every phase up to
# and including its last recorded one, reusing cached engine_result rows instead
# of re-running GPU inference.
PHASE_ENGINE_A_DONE = "engine_a_done"
PHASE_ENGINE_B_DONE = "engine_b_done"
PHASE_RECONCILED = "reconciled"
PHASE_WRITTEN = "written"

# The pseudo-Engine-B label. Not a registry name — nothing may ever try to
# construct it (see `canonical_engine_names`).
SELF_ENSEMBLE = "self_ensemble"


@dataclass(frozen=True)
class JobPlan:
    """What this run will do, decided before any model is touched.

    A value, so it can be logged: a maintainer debugging a resumed job can see
    what the pipeline decided rather than inferring it from behaviour.
    """

    engine_a_name: str
    engine_b_name: str
    self_ensemble_enabled: bool
    # Decode overrides for the self-ensemble pair. None everywhere when
    # self-ensemble is off, which is what preserves each engine's own defaults.
    temperature_a: float | None
    beam_size_a: int | None
    temperature_b: float | None
    beam_size_b: int | None
    # Resume: skip a phase whose result is already cached in engine_result.
    skip_engine_a: bool
    skip_engine_b: bool
    # Capability-derived, from the engine classes — no instance needed.
    chunk_engine_active: bool
    needs_full_audio: bool
    engine_batch_size: int
    chunk_overlap_ms: int


def canonical_engine_names(config: dict) -> tuple[str, str]:
    """(engine_a_name, engine_b_name) — the ONE derivation of job identity.

    HANDOFF_ONE_ENGINE §6 (Phase D) — N-best self-ensemble: pseudo-Engine-B is a
    SECOND decode pass through Engine A's own already-loaded residency (different
    temperature/beam_size), not a second model. Zero extra VRAM/load cost.
    `engine_b_name` is forced to a canonical label here — independent of whatever
    `config["engine_b"]` literally says — so job/engine_result identity (and
    `store.find_resumable_job`'s resume key) is coherent regardless of entry
    point (config.yaml edit vs harness --self-ensemble CLI flag). Getting this
    from harness.py's CLI-only convention instead would let a config.yaml-only
    activation silently mislabel engine_result rows as the wrong engine AND let a
    self-ensemble job cross-resume into a genuine passthrough job's cached
    results for the same media (found in review 2026-08-05 — see TODO_LEDGER.md).

    This lives in one function precisely because that defect was two entry points
    reaching the same state by different paths, with nothing pure enough to test
    the agreement.
    """
    engine_a_name = config["engine_a"]
    if _self_ensemble_cfg(config).get("enabled", False):
        return engine_a_name, SELF_ENSEMBLE
    return engine_a_name, config["engine_b"]


def make_plan(config: dict, resume_phase: str | None) -> JobPlan:
    """Decide everything about this run from config plus the resumed job's phase.

    Raises ValueError if `self_ensemble.enabled` is set with a chunk-based Engine
    A — a hard error, unchanged in message and in raising behaviour, but now
    reachable without constructing an engine.
    """
    engine_a_name, engine_b_name = canonical_engine_names(config)
    cfg = _self_ensemble_cfg(config)
    enabled = bool(cfg.get("enabled", False))

    if enabled and not registry.prefers_whole_file(engine_a_name):
        raise ValueError(
            "self_ensemble.enabled requires a whole-file Engine A "
            f"(prefers_whole_file=True) — {engine_a_name!r} is chunk-based. "
            "The self-ensemble pseudo-B is a second decode pass through "
            "Engine A's own residency; there is no per-chunk restitch path."
        )

    # Only Engine A is a real engine under self-ensemble, so only it can make
    # this a chunk run or demand the full track.
    def _is_chunk(name: str) -> bool:
        # passthrough consumes nothing; whole-file engines want the raw track.
        return name != "passthrough" and not registry.prefers_whole_file(name)

    if enabled:
        chunk_engine_active = _is_chunk(engine_a_name)
        needs_full_audio = registry.prefers_whole_file(engine_a_name)
    else:
        chunk_engine_active = _is_chunk(engine_a_name) or _is_chunk(engine_b_name)
        needs_full_audio = (registry.prefers_whole_file(engine_a_name)
                            or registry.prefers_whole_file(engine_b_name))

    return JobPlan(
        engine_a_name=engine_a_name,
        engine_b_name=engine_b_name,
        self_ensemble_enabled=enabled,
        temperature_a=_opt_float(cfg.get("temperature_a", 0.0)) if enabled else None,
        beam_size_a=_opt_int(cfg.get("beam_size_a")) if enabled else None,
        temperature_b=_opt_float(cfg.get("temperature_b", 0.2)) if enabled else None,
        beam_size_b=_opt_int(cfg.get("beam_size_b", 1)) if enabled else None,
        skip_engine_a=resume_phase in (PHASE_ENGINE_A_DONE, PHASE_ENGINE_B_DONE,
                                        PHASE_RECONCILED, PHASE_WRITTEN),
        skip_engine_b=resume_phase in (PHASE_ENGINE_B_DONE, PHASE_RECONCILED,
                                        PHASE_WRITTEN),
        chunk_engine_active=chunk_engine_active,
        needs_full_audio=needs_full_audio,
        engine_batch_size=int(config.get("engine_batch_size", 8)),
        chunk_overlap_ms=int(config.get("chunk_overlap_ms", 750)),
    )


def _self_ensemble_cfg(config: dict) -> dict:
    return config.get("self_ensemble", {}) or {}


def _opt_float(value) -> float | None:
    return float(value) if value is not None else None


def _opt_int(value) -> int | None:
    return int(value) if value is not None else None
