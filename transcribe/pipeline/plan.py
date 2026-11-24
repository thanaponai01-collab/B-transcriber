from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from transcribe.engines import registry

PHASE_ENGINE_A_DONE = "engine_a_done"
PHASE_ENGINE_B_DONE = "engine_b_done"
PHASE_RECONCILED = "reconciled"
PHASE_WRITTEN = "written"

SELF_ENSEMBLE = "self_ensemble"


@dataclass(frozen=True)
class JobPlan:
    engine_a_name: str
    engine_b_name: str
    self_ensemble_enabled: bool
    temperature_a: float | None
    beam_size_a: int | None
    temperature_b: float | None
    beam_size_b: int | None
    skip_engine_a: bool
    skip_engine_b: bool
    chunk_engine_active: bool
    needs_full_audio: bool
    engine_batch_size: int
    chunk_overlap_ms: int
    language: str = "th"


def canonical_engine_names(config: dict) -> tuple[str, str]:
    """(engine_a_name, engine_b_name): the one derivation of job identity.

    With self-ensemble on, `engine_b_name` is forced to a canonical label whatever
    `config["engine_b"]` says, so `store.find_resumable_job`'s resume key is the
    same from a config.yaml edit or the harness `--self-ensemble` flag.
    """
    engine_a_name = config["engine_a"]
    if _self_ensemble_cfg(config).get("enabled", False):
        return engine_a_name, SELF_ENSEMBLE
    return engine_a_name, config["engine_b"]


def make_plan(config: dict, resume_phase: str | None) -> JobPlan:
    """Decide everything about this run from config plus the resumed job's phase.

    Raises ValueError if `self_ensemble.enabled` is set with a chunk-based Engine A.
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

    def _is_chunk(name: str) -> bool:
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
        language=str(config.get("language") or "th"),
    )


def _self_ensemble_cfg(config: dict) -> dict:
    return config.get("self_ensemble", {}) or {}


def _opt_float(value) -> float | None:
    return float(value) if value is not None else None


def _opt_int(value) -> int | None:
    return int(value) if value is not None else None


def resume_fingerprint(config: dict, bias_terms: list[str], bias_weights: dict) -> str:
    """Conservative cache identity: all settings and the exact bias inputs.

    Mapping order is immaterial; list order (including prompt term order) is not.
    Local checkpoint contents changed in place still require a version bump.
    """
    payload = {"config": config, "bias_terms": bias_terms, "bias_weights": bias_weights}
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
