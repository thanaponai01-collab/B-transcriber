from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import NamedTuple

from transcribe.console import safe_print as _safe_print
from transcribe.db import store
from transcribe.eval.gate import decide
from transcribe.eval import robustness as robust
from transcribe.eval.metrics import CI_METRICS, EvalMetrics, bootstrap_ci, compute_metrics, paired_bootstrap_ci
from transcribe.thai.atoms import default_lexicon
from transcribe.thai.lint import find_cue_legality_violations

_GOLDENSET = Path(__file__).parent / "goldenset"


class HarnessResult(NamedTuple):
    """Callers must consume `passed` — never re-read get_last_passing_eval
    (that would compare the new run against itself)."""
    metrics: EvalMetrics
    passed: bool
    baseline: store.EvalRunRow | None
    rtf: float | None = None
    ci: dict[str, tuple[float, float]] | None = None
    unresolved: list[str] | None = None
    status: str = "pass"
    paired_ci: dict[str, tuple[float, float]] | None = None


def _config_hash(config: dict) -> str:
    blob = json.dumps(config, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def _pipeline_version() -> str:
    try:
        from transcribe.pipeline.run import PIPELINE_VERSION
        return PIPELINE_VERSION
    except Exception:
        return "unknown"


def _bias_hash(conn) -> str:
    terms = sorted(store.get_bias_term_strings(conn))
    return hashlib.sha256("\n".join(terms).encode()).hexdigest()[:16]


def _media_extensions() -> tuple[str, ...]:
    from transcribe.pipeline.ingest import _AV_CONTAINERS
    return (".wav", ".mp3", ".flac") + tuple(sorted(_AV_CONTAINERS))


def _audio_duration_s(path: Path) -> float:
    try:
        from transcribe.pipeline.ingest import load_audio
        samples, sr = load_audio(str(path))
        return len(samples) / sr if sr else 0.0
    except Exception:
        return 0.0


def _load_goldenset() -> list[tuple[Path, list[dict]]]:
    samples = []
    for gt_file in sorted(_GOLDENSET.glob("*.json")):
        audio_candidates = [gt_file.with_suffix(ext) for ext in _media_extensions()]
        audio_file = next((p for p in audio_candidates if p.exists()), None)
        if audio_file is None:
            print(f"[harness] WARNING: no audio for {gt_file.name}, skipping")
            continue
        ref = json.loads(gt_file.read_text(encoding="utf-8"))
        samples.append((audio_file, ref["tokens"]))
    return samples



def _cue_excluded(audio_path: Path, config: dict) -> bool:
    return audio_path.stem in (config.get("eval_cue_metric_exclude") or [])


def _clip_key(audio_path: Path, ref_tokens: list[dict], config: dict,
              *, audio_sha256: str | None = None) -> str:
    if audio_sha256 is not None:
        audio_hash = audio_sha256
    else:
        audio_hash = (store.sha256_of_file(str(audio_path)) if audio_path.is_file()
                      else "missing:" + audio_path.as_posix())
    payload = {"sample": audio_path.stem, "audio": audio_hash, "reference": ref_tokens,
               "normalization": config.get("normalization", {}),
               "boundary_tol_ms": float(config.get("boundary_tol_ms", 300.0))}
    if _cue_excluded(audio_path, config):
        payload["cue_metric_excluded"] = True
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class _Item(NamedTuple):
    gold_path: Path
    run_path: Path
    ref_tokens: list[dict]
    key: str
    condition: str | None


def _condition_id(cond: robust.Condition, music_sha: str | None) -> str:
    payload = json.dumps([cond._asdict(), music_sha if cond.music_snr_db is not None else None],
                         sort_keys=True)
    return f"{cond.name}-{hashlib.sha256(payload.encode()).hexdigest()[:12]}"


def _robustness_items(samples, config: dict, out_dir: Path) -> list[_Item]:
    import soundfile as sf
    from transcribe.pipeline.ingest import load_audio
    music_path = (config.get("eval_robustness") or {}).get("music_bed")
    music = music_sha = None
    if music_path:
        music_file = Path(music_path)
        music_file = music_file if music_file.is_absolute() else _GOLDENSET.parents[2] / music_file
        music, _ = load_audio(str(music_file))
        music_sha = store.sha256_of_file(str(music_file))
    items = []
    for n, (gold_path, ref_tokens) in enumerate(samples):
        audio, sr = load_audio(str(gold_path))
        base_key = _clip_key(gold_path, ref_tokens, config)
        for cond in robust.CONDITIONS:
            cond_id = _condition_id(cond, music_sha)
            run_path = out_dir / f"{n:02d}_{cond.name}.wav"
            sf.write(str(run_path), robust.perturb(audio, sr, cond, music), sr, subtype="FLOAT")
            items.append(_Item(gold_path, run_path, ref_tokens, f"{cond_id}|{base_key}", cond_id))
    return items


def _by_condition(clips_by_key: dict[str, EvalMetrics]) -> dict[str, list[EvalMetrics]]:
    grouped: dict[str, list[EvalMetrics]] = {}
    for key in sorted(clips_by_key, key=lambda k: k.split("|", 1)[::-1]):
        grouped.setdefault(key.split("|", 1)[0], []).append(clips_by_key[key])
    return grouped


def run_harness(
    config: dict,
    db_path: Path,
    pipeline_fn=None,
    experiment: bool = False,
    establish_baseline: bool = False,
    robustness: bool = False,
) -> HarnessResult | None:
    """
    Run the golden set through the pipeline and compute aggregate metrics.

    Args:
        config: dict with at least {"engine_a": str, "engine_b": str, ...}
        db_path: path to the SQLite database
        pipeline_fn: callable(audio_path, config) -> list[dict{"text","script"}]
                     If None, the real pipeline is used (imports pipeline.run).
        establish_baseline: Explicit production re-evaluation to seed per-clip
                            evidence, skipping historical comparisons but not
                            structural checks. Incompatible with experiments.
        experiment: True for an A/B probe (e.g. `--engine-b X`, `--llm-enabled`).
                    The run is still gated against the production baseline, but
                    its eval_run row is marked is_experiment=1 so it can never
                    BECOME the baseline a later production run is compared to.
                    Production config changes (engine swap in config.yaml, bias
                    promotion) stay experiment=False — the gate must compare
                    them against the previous production baseline and, on pass,
                    only a confirmed pass becomes the new one.
        robustness: decode every gold clip under each `robustness.CONDITIONS` entry and
                    gate the pooled metrics plus `cer_thai_spread` against the last
                    production robustness run (`eval_run.kind = 'robustness'`).
    """
    if establish_baseline and experiment:
        raise ValueError("baseline establishment requires a production run, not an experiment")
    store.init_db(db_path)
    samples = _load_goldenset()
    if not samples:
        print("[harness] WARNING: goldenset is empty - add audio+json pairs to "
              "eval/goldenset/. No eval_run recorded.")
        return None

    scratch_dir: Path | None = None
    scratch_db: Path | None = None
    warm_engine_a = None
    using_real_pipeline = pipeline_fn is None
    if using_real_pipeline:
        import torch
        from transcribe.pipeline import engine_run
        from transcribe.pipeline import run as pipeline_run
        scratch_dir = Path(tempfile.mkdtemp(prefix="eval_scratch_"))
        scratch_db = scratch_dir / "scratch.db"
        store.init_db(scratch_db)
        _src = store.connect(db_path)
        _dst = store.connect(scratch_db)
        for _t in store.get_bias_terms(_src):
            store.upsert_bias_term(_dst, _t.term, _t.term_type, _t.script, _t.added_by, _t.weight)
        _src.close()
        _dst.close()

        if config.get("engine_a") and not (config.get("word_align") or {}).get("enabled") and (
            config.get("engine_b", "passthrough") == "passthrough"
            or bool((config.get("self_ensemble") or {}).get("enabled", False))
        ):
            device = "cuda" if torch.cuda.is_available() else "cpu"
            warm_engine_a = engine_run.build_engine(config["engine_a"], device, config)
            warm_engine_a.load()

    tol = float(config.get("boundary_tol_ms", 300.0))
    kind = "robustness" if robustness else "transcribe"
    perturbed_dir = Path(tempfile.mkdtemp(prefix="eval_robust_")) if robustness else None
    if robustness:
        items = _robustness_items(samples, config, perturbed_dir)
    else:
        items = [_Item(p, p, ref, "", None) for p, ref in samples]

    clip_metrics: list[EvalMetrics] = []
    clips_by_key: dict[str, EvalMetrics] = {}
    total_wall_s = 0.0
    total_audio_s = 0.0
    lexicon = default_lexicon(config)
    total_hyp_lint_violations = 0
    total_ref_lint_violations = 0

    try:
        for gold_path, audio_path, ref_tokens, key, _condition in items:
            file_sha256 = store.sha256_of_file(str(audio_path)) if audio_path.is_file() else None
            key = key or _clip_key(audio_path, ref_tokens, config, audio_sha256=file_sha256)
            if key in clips_by_key:
                raise ValueError(f"duplicate golden sample: {audio_path}")
            t0 = time.perf_counter()
            if using_real_pipeline:
                try:
                    hyp_tokens = pipeline_run.run_file(
                        str(audio_path), config, scratch_db,
                        sha256=file_sha256, engine_a=warm_engine_a,
                    )
                except TypeError:
                    hyp_tokens = pipeline_run.run_file(str(audio_path), config, scratch_db)
            else:
                hyp_tokens = pipeline_fn(audio_path, config)
            total_wall_s += time.perf_counter() - t0
            if using_real_pipeline and scratch_db is not None and file_sha256 is not None:
                _sconn = store.connect(scratch_db)
                try:
                    _media = store.get_media_by_sha256(_sconn, file_sha256)
                finally:
                    _sconn.close()
                if _media is not None and _media.duration_ms is not None:
                    total_audio_s += _media.duration_ms / 1000.0
                else:
                    total_audio_s += _audio_duration_s(audio_path)
            else:
                total_audio_s += _audio_duration_s(audio_path)
            m = compute_metrics(ref_tokens, hyp_tokens, config=config, boundary_tol_ms=tol)
            if _cue_excluded(gold_path, config):
                m = dataclasses.replace(m, ref_cues=0, hyp_cues=0, matched_cues=0, cue_boundary_error_rate=0.0)
            clip_metrics.append(m)
            clips_by_key[key] = m

            hyp_violations = find_cue_legality_violations(hyp_tokens, lexicon)
            ref_violations = find_cue_legality_violations(ref_tokens, lexicon)
            total_hyp_lint_violations += len(hyp_violations)
            total_ref_lint_violations += len(ref_violations)
            if hyp_violations:
                detail = "; ".join(f"{v.rule}[{v.index}]={v.detail!r}" for v in hyp_violations)
                _safe_print(f"[harness] cue_legality VIOLATION {audio_path.stem}: {detail}")
            if ref_violations:
                detail = "; ".join(f"{v.rule}[{v.index}]={v.detail!r}" for v in ref_violations)
                _safe_print(f"[harness] cue_legality REFERENCE also violates (lexicon may be wrong, "
                            f"not a hyp bug) {audio_path.stem}: {detail}")
    finally:
        if warm_engine_a is not None:
            try:
                warm_engine_a.unload()
            finally:
                del warm_engine_a
                engine_run._free_vram()
        if scratch_dir is not None:
            shutil.rmtree(scratch_dir, ignore_errors=True)
        if perturbed_dir is not None:
            shutil.rmtree(perturbed_dir, ignore_errors=True)

    by_condition = _by_condition(clips_by_key) if robustness else None
    agg = robust.pooled(by_condition) if robustness else EvalMetrics.aggregate(clip_metrics)
    spread = robust.cer_thai_spread(by_condition) if robustness else None
    gate_names = robust.ROBUST_METRICS if robustness else CI_METRICS

    conn = store.connect(db_path)
    cfg_hash = _config_hash(config)

    if robustness:
        ci_bounds = {name: robust.bootstrap_ci(by_condition, name) for name in gate_names}
    else:
        ci_bounds = {name: bootstrap_ci(clip_metrics, name) for name in CI_METRICS}
    rtf = total_wall_s / total_audio_s if total_audio_s > 0 else None

    tol_frac = 1.0 + float(config.get("regression_tolerance", 0.02))
    abs_floor = float(config.get("regression_abs_floor", 0.005))
    last = None if establish_baseline else store.get_last_passing_eval(conn, kind=kind)
    paired_ci = None
    comparison_error = None
    if establish_baseline:
        print("[harness] establishing a paired production baseline (history preserved)")
    if last is not None:
        cached = store.get_eval_clip_metrics(conn, last.id)
        if not cached:
            comparison_error = "baseline has no per-clip evidence; re-evaluate with --establish-baseline"
        elif set(cached) != set(clips_by_key):
            comparison_error = "gold audio, reference or scoring policy differs; cannot pair runs"
        elif robustness:
            previous = _by_condition({k: EvalMetrics(**json.loads(v)) for k, v in cached.items()})
            paired_ci = {name: robust.paired_bootstrap_ci(by_condition, previous, name)
                         for name in gate_names}
        else:
            keys = sorted(clips_by_key)
            current = [clips_by_key[key] for key in keys]
            previous = [EvalMetrics(**json.loads(cached[key])) for key in keys]
            paired_ci = {name: paired_bootstrap_ci(current, previous, name) for name in CI_METRICS}
    verdict = decide(agg, last, paired_ci, tol_frac, abs_floor, comparison_error=comparison_error,
                     names=gate_names)
    if paired_ci is not None:
        bands = "; ".join(f"{name}=[{lo:.4f},{hi:.4f}]" for name, (lo, hi) in paired_ci.items())
        print(f"[harness] paired delta 95% CIs vs eval_run {last.id}: {bands}")
    passed = verdict.passed
    if verdict.regressions:
        print("[harness] REGRESSION: " + "; ".join(verdict.regressions))
    if verdict.unresolved:
        print("[harness] UNRESOLVED (not a confirmed pass or regression): "
              + "; ".join(verdict.unresolved))

    if verdict.improvements:
        print("[harness] CONFIRMED IMPROVEMENT: " + "; ".join(verdict.improvements))

    if agg.overlapping_cues > 0:
        print(f"[harness] HARD FAIL: {agg.overlapping_cues} overlapping cue(s) in hypothesis output")

    gate_unresolved_names = verdict.gate_unresolved

    store.create_eval_run(conn, store.EvalRun(
        config_hash=cfg_hash,
        wer=agg.wer,
        boundary_error_rate=agg.boundary_error_rate,
        passed=passed,
        cer_thai=agg.cer_thai,
        wer_latin=agg.wer_latin,
        kind=kind,
        pipeline_version=_pipeline_version(),
        engine_pair=f"{config.get('engine_a', '?')}+{config.get('engine_b', '?')}",
        bias_hash=_bias_hash(conn),
        is_experiment=experiment,
        cue_boundary_error_rate=agg.cue_boundary_error_rate,
        overlapping_cues=agg.overlapping_cues,
        cue_count_delta=agg.cue_count_delta,
        shortest_cue_ms=agg.shortest_cue_ms,
        nonzero_gap_count=agg.nonzero_gap_count,
        cer_thai_ci_lo=ci_bounds["cer_thai"][0], cer_thai_ci_hi=ci_bounds["cer_thai"][1],
        wer_latin_ci_lo=ci_bounds["wer_latin"][0], wer_latin_ci_hi=ci_bounds["wer_latin"][1],
        boundary_error_rate_ci_lo=ci_bounds["boundary_error_rate"][0],
        boundary_error_rate_ci_hi=ci_bounds["boundary_error_rate"][1],
        cue_boundary_error_rate_ci_lo=ci_bounds["cue_boundary_error_rate"][0],
        cue_boundary_error_rate_ci_hi=ci_bounds["cue_boundary_error_rate"][1],
        speech_coverage_miss=agg.speech_coverage_miss,
        orphan_cues=agg.orphan_cues,
        speech_coverage_miss_ci_lo=ci_bounds["speech_coverage_miss"][0],
        speech_coverage_miss_ci_hi=ci_bounds["speech_coverage_miss"][1],
        cer_thai_sub=agg.thai_sub / agg.thai_chars if agg.thai_chars else 0.0,
        cer_thai_del=agg.thai_del / agg.thai_chars if agg.thai_chars else 0.0,
        cer_thai_ins=agg.thai_ins / agg.thai_chars if agg.thai_chars else 0.0,
        cer_thai_spread=spread,
        cer_thai_spread_ci_lo=ci_bounds["cer_thai_spread"][0] if robustness else None,
        cer_thai_spread_ci_hi=ci_bounds["cer_thai_spread"][1] if robustness else None,
        rtf=rtf,
        gate_unresolved=gate_unresolved_names,
        cue_legality_violations=total_hyp_lint_violations,
        baseline_eval_id=last.id if last is not None else None,
        paired_delta_ci_json=json.dumps(paired_ci) if paired_ci is not None else None,
        gate_status=verdict.status,
    ), clip_metrics={key: json.dumps(dataclasses.asdict(m)) for key, m in clips_by_key.items()})
    conn.close()

    def _fmt_ci(name: str) -> str:
        lo, hi = ci_bounds[name]
        return f"[{lo:.4f},{hi:.4f}]"

    if agg.thai_chars:
        print(f"[harness] CER_thai breakdown: sub={agg.thai_sub / agg.thai_chars:.4f} "
              f"del={agg.thai_del / agg.thai_chars:.4f} ins={agg.thai_ins / agg.thai_chars:.4f} "
              f"(counts {agg.thai_sub}/{agg.thai_del}/{agg.thai_ins} of {agg.thai_chars})")
    if robustness:
        for name, clips in by_condition.items():
            m = EvalMetrics.aggregate(clips)
            print(f"[harness] condition {name.rsplit('-', 1)[0]:>8}: "
                  f"CER_thai={m.cer_thai:.4f} sub={m.thai_sub} del={m.thai_del} ins={m.thai_ins}  "
                  f"cue_BER={m.cue_boundary_error_rate:.4f} coverage_miss={m.speech_coverage_miss:.4f}")
        print(f"[harness] CER_thai spread={spread:.4f} {_fmt_ci('cer_thai_spread')} (pooled figures below)")
    print(
        f"[harness] CER_thai={agg.cer_thai:.4f} {_fmt_ci('cer_thai')}  "
        f"WER_latin={agg.wer_latin:.4f} {_fmt_ci('wer_latin')}  "
        f"BER={agg.boundary_error_rate:.4f} {_fmt_ci('boundary_error_rate')}  "
        f"WER={agg.wer:.4f}  "
        f"cue_BER={agg.cue_boundary_error_rate:.4f} {_fmt_ci('cue_boundary_error_rate')}  "
        f"coverage_miss={agg.speech_coverage_miss:.4f} {_fmt_ci('speech_coverage_miss')}  "
        f"orphans={agg.orphan_cues}  "
        f"cue_overlaps={agg.overlapping_cues}  cue_count_delta={agg.cue_count_delta:+d}  "
        f"cue_legality_violations={total_hyp_lint_violations} "
        f"(reference={total_ref_lint_violations})  "
        f"rtf={'n/a' if rtf is None else f'{rtf:.3f}'}  "
        f"thai_chars={agg.thai_chars}  latin_words={agg.latin_words}  "
        f"switches={agg.ref_switches} (hyp {agg.hyp_switches}, matched {agg.matched_switches})  "
        f"status={verdict.status} passed={passed}"
    )
    return HarnessResult(metrics=agg, passed=passed, baseline=last,
                          rtf=rtf, ci=ci_bounds, unresolved=verdict.unresolved or None,
                          status=verdict.status, paired_ci=paired_ci)


if __name__ == "__main__":
    import argparse, yaml
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--db", default=None,
                        help="Eval database; default is store.path from config.yaml")
    parser.add_argument("--engine-b", help="Override engine_b for a one-command A/B "
                        "comparison, e.g. --engine-b whisper_multi (4.2)")
    parser.add_argument("--llm-enabled", action="store_true",
                        help="Turn on the local-Ollama LLM reconciler tiebreak for this "
                        "run, for an A/B comparison against the script fallback (Phase 3)")
    parser.add_argument("--self-ensemble", action="store_true",
                        help="Turn on the N-best self-ensemble (HANDOFF_ONE_ENGINE §6, "
                        "Phase D): pseudo-Engine-B is a second decode pass through "
                        "Engine A's own residency at self_ensemble.temperature_b, no "
                        "second model load. Sets engine_b to 'self_ensemble' for the "
                        "eval_run label.")
    parser.add_argument("--self-ensemble-temp-b", type=float, default=None,
                        help="Override self_ensemble.temperature_b for this run "
                        "(default from config.yaml, normally 0.2 — documented no-op unless "
                        "beam_size_b==1, see config.yaml's self_ensemble comment). Implies "
                        "--self-ensemble.")
    parser.add_argument("--self-ensemble-beam-b", type=int, default=None,
                        help="Override self_ensemble.beam_size_b for this run (default from "
                        "config.yaml, normally 1 — the setting that actually produces a "
                        "decorrelated second hypothesis). Implies --self-ensemble.")
    parser.add_argument("--establish-baseline", action="store_true",
                        help="Re-evaluate production to establish matching per-clip baseline evidence. "
                             "Preserves history and cue-overlap checks; cannot be combined with experiments.")
    parser.add_argument("--robustness", action="store_true",
                        help="Decode every gold clip under each recording condition in "
                        "transcribe/eval/robustness.py (gain, noise, music bed) and gate the pooled "
                        "metrics plus cer_thai_spread against the last production robustness run.")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="Override one config value for this run, e.g. "
                        "--set engines.faster_whisper.compute_type=int8_float16 (VALUE is YAML). "
                        "Repeatable; implies --experiment.")
    parser.add_argument("--experiment", action="store_true",
                        help="Mark this run as an A/B experiment: gated against the "
                        "production baseline but never recorded AS a baseline. Implied "
                        "by --engine-b / --llm-enabled / --self-ensemble (those override "
                        "config.yaml, so their runs don't describe the production config).")
    args = parser.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    self_ensemble = bool(args.self_ensemble or args.self_ensemble_temp_b is not None
                          or args.self_ensemble_beam_b is not None)
    experiment = bool(args.experiment or args.engine_b or args.llm_enabled or self_ensemble or args.set)
    for override in args.set:
        dotted, _, raw = override.partition("=")
        *parents, leaf = dotted.split(".")
        node = cfg
        for part in parents:
            node = node.setdefault(part, {})
        node[leaf] = yaml.safe_load(raw)
        print(f"[harness] override {dotted} = {node[leaf]!r}")
    if args.engine_b:
        cfg["engine_b"] = args.engine_b
    if args.llm_enabled:
        cfg.setdefault("reconciler", {})["llm_enabled"] = True
    if self_ensemble:
        se_cfg = cfg.setdefault("self_ensemble", {})
        se_cfg["enabled"] = True
        if args.self_ensemble_temp_b is not None:
            se_cfg["temperature_b"] = args.self_ensemble_temp_b
        if args.self_ensemble_beam_b is not None:
            se_cfg["beam_size_b"] = args.self_ensemble_beam_b
        cfg["engine_b"] = "self_ensemble"
    if experiment:
        print("[harness] experiment run - result will not become the regression baseline")
    import sys
    result = run_harness(cfg, Path(args.db) if args.db else store.resolve_db_path(cfg), experiment=experiment,
                         establish_baseline=args.establish_baseline, robustness=args.robustness)
    if result is not None and result.status == "unresolved":
        sys.exit(2)
    if result is None or not result.passed:
        sys.exit(1)
