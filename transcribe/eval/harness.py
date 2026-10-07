"""Eval harness — runs a pipeline config over the golden set and records metrics."""

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
from transcribe.eval.metrics import CI_METRICS, EvalMetrics, bootstrap_ci, compute_metrics, paired_bootstrap_ci
from transcribe.thai.atoms import default_lexicon
from transcribe.thai.lint import find_cue_legality_violations

_GOLDENSET = Path(__file__).parent / "goldenset"

# _safe_print was born here (Thai cue-legality details crashing a cp1252 console)
# and now lives in transcribe.console, because the CutDeck exporters hit the same
# wall on Thai media paths. Aliased rather than renamed at ~4 call sites below.


class HarnessResult(NamedTuple):
    """The harness is the single gate authority: it captures the prior passing
    baseline *before* writing the new eval_run, gates on all four paired
    signals, and returns its verdict. Callers must consume `passed` — never
    re-read get_last_passing_eval (that would compare the new run against itself)."""
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
    """Read the live pipeline version without importing the GPU stack at module load."""
    try:
        from transcribe.pipeline.run import PIPELINE_VERSION
        return PIPELINE_VERSION
    except Exception:
        return "unknown"


def _bias_hash(conn) -> str:
    """Hash of the active bias index — makes a regression attributable to the
    exact term set that produced it (A.2)."""
    terms = sorted(store.get_bias_term_strings(conn))
    return hashlib.sha256("\n".join(terms).encode()).hexdigest()[:16]


def _media_extensions() -> tuple[str, ...]:
    """Every extension the pipeline can actually ingest (audio + AV containers) —
    a gold sample's source clip is frequently a raw video export, not audio-only."""
    from transcribe.pipeline.ingest import _AV_CONTAINERS
    return (".wav", ".mp3", ".flac") + tuple(sorted(_AV_CONTAINERS))


def _audio_duration_s(path: Path) -> float:
    """Best-effort audio duration in seconds, for RTF (wall-clock decode time
    ÷ audio duration, HANDOFF_ONE_ENGINE §3.1). Returns 0.0 on any failure —
    e.g. the synthetic `Path("fake.wav")` fixtures unit tests pass as
    pipeline_fn's audio_path — so a clip that can't be duration-probed just
    doesn't contribute to RTF rather than crashing the run; RTF is
    descriptive-only, never gated."""
    try:
        from transcribe.pipeline.ingest import load_audio
        samples, sr = load_audio(str(path))
        return len(samples) / sr if sr else 0.0
    except Exception:
        return 0.0


def _load_goldenset() -> list[tuple[Path, list[dict]]]:
    """Return [(audio_path, ref_tokens), ...] for every sample in the golden set."""
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
    """True when the clip's reference cues aren't subtitle-sized (config
    `eval_cue_metric_exclude`, by sample stem), so it can't score segmentation."""
    return audio_path.stem in (config.get("eval_cue_metric_exclude") or [])


def _clip_key(audio_path: Path, ref_tokens: list[dict], config: dict) -> str:
    """Pair only identical media, references and scoring policies.

    Missing paths support synthetic pipeline_fn fixtures; real gold media are
    content-hashed. Sample names keep identical-content clips distinct.
    """
    audio_hash = (store.sha256_of_file(str(audio_path)) if audio_path.is_file()
                  else "missing:" + audio_path.as_posix())
    payload = {"sample": audio_path.stem, "audio": audio_hash, "reference": ref_tokens,
               "normalization": config.get("normalization", {}),
               "boundary_tol_ms": float(config.get("boundary_tol_ms", 300.0))}
    if _cue_excluded(audio_path, config):
        payload["cue_metric_excluded"] = True
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def run_harness(
    config: dict,
    db_path: Path,
    pipeline_fn=None,
    experiment: bool = False,
    establish_baseline: bool = False,
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
    Returns:
        EvalMetrics aggregate over all golden samples.
    """
    if establish_baseline and experiment:
        raise ValueError("baseline establishment requires a production run, not an experiment")
    store.init_db(db_path)
    # #5: eval transcription writes media/job/token rows. Keep those OUT of the
    # caller's DB (the editor and flywheel read it) by sending run_file to a
    # throwaway scratch DB. eval_run *history* still goes to db_path below, so the
    # regression gate stays coherent across runs.
    scratch_dir: Path | None = None
    if pipeline_fn is None:
        from transcribe.pipeline import run as pipeline_run
        scratch_dir = Path(tempfile.mkdtemp(prefix="eval_scratch_"))
        scratch_db = scratch_dir / "scratch.db"
        store.init_db(scratch_db)
        # run_file reads its bias index from the DB it runs against. A fresh
        # scratch DB has no bias terms, so the eval would silently measure a
        # prompt-less pipeline — the one thing a bias-update gate must not do.
        # Mirror the live bias index into the scratch DB before any sample runs.
        _src = store.connect(db_path)
        _dst = store.connect(scratch_db)
        for _t in store.get_bias_terms(_src):
            store.upsert_bias_term(_dst, _t.term, _t.term_type, _t.script, _t.added_by, _t.weight)
        _src.close()
        _dst.close()
        def pipeline_fn(audio_path, cfg):
            return pipeline_run.run_file(str(audio_path), cfg, scratch_db)

    samples = _load_goldenset()
    if not samples:
        # An empty gold set scores 0.0 on every metric. Writing that as a passing
        # eval_run poisons the baseline: the gate is `new > last × 1.02`, so a
        # zero baseline makes every future real run fail forever. Refuse to write.
        print("[harness] WARNING: goldenset is empty - add audio+json pairs to "
              "eval/goldenset/. No eval_run recorded.")
        if scratch_dir is not None:
            shutil.rmtree(scratch_dir, ignore_errors=True)
        return None

    tol = float(config.get("boundary_tol_ms", 300.0))

    # Corpus aggregation is EvalMetrics.aggregate's job — each metric's weighting
    # rule lives next to its definition, so the two cannot silently disagree.
    clip_metrics: list[EvalMetrics] = []
    clips_by_key: dict[str, EvalMetrics] = {}
    total_wall_s = 0.0
    total_audio_s = 0.0
    # Phase 3 cue-legality lint (HANDOFF_THAI_BREAK_ATOMS.md §5): shares the
    # splitter's own BreakLexicon so the lint can never drift from what
    # glue_atoms actually protects.
    lexicon = default_lexicon(config)
    total_hyp_lint_violations = 0
    total_ref_lint_violations = 0

    for audio_path, ref_tokens in samples:
        key = _clip_key(audio_path, ref_tokens, config)
        if key in clips_by_key:
            raise ValueError(f"duplicate golden sample: {audio_path}")
        t0 = time.perf_counter()
        hyp_tokens = pipeline_fn(audio_path, config)
        total_wall_s += time.perf_counter() - t0
        total_audio_s += _audio_duration_s(audio_path)
        # Pass config so reference and hypothesis are normalized identically.
        m = compute_metrics(ref_tokens, hyp_tokens, config=config, boundary_tol_ms=tol)
        if _cue_excluded(audio_path, config):
            # Zero only the cue-boundary micro-F1 inputs: text metrics and the
            # overlapping_cues hard invariant still count this clip.
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
            # The gold recuts define taste — a violation the reference also
            # commits means the lexicon is wrong, not the hypothesis. Printed,
            # never hidden (§5).
            detail = "; ".join(f"{v.rule}[{v.index}]={v.detail!r}" for v in ref_violations)
            _safe_print(f"[harness] cue_legality REFERENCE also violates (lexicon may be wrong, "
                        f"not a hyp bug) {audio_path.stem}: {detail}")

    if scratch_dir is not None:
        shutil.rmtree(scratch_dir, ignore_errors=True)

    agg = EvalMetrics.aggregate(clip_metrics)

    conn = store.connect(db_path)
    cfg_hash = _config_hash(config)

    # Bootstrap CIs (Phase A, HANDOFF_ONE_ENGINE §3.1): resample clips, not
    # just report a point estimate. n_draws=1000 is cheap at this corpus size
    # (thousands of clip-count-sized resamples, no re-transcription involved).
    ci_bounds = {name: bootstrap_ci(clip_metrics, name) for name in CI_METRICS}
    rtf = total_wall_s / total_audio_s if total_audio_s > 0 else None

    tol_frac = 1.0 + float(config.get("regression_tolerance", 0.02))
    abs_floor = float(config.get("regression_abs_floor", 0.005))
    last = None if establish_baseline else store.get_last_passing_eval(conn)
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
        else:
            keys = sorted(clips_by_key)
            current = [clips_by_key[key] for key in keys]
            previous = [EvalMetrics(**json.loads(cached[key])) for key in keys]
            paired_ci = {name: paired_bootstrap_ci(current, previous, name) for name in CI_METRICS}
    verdict = decide(agg, last, paired_ci, tol_frac, abs_floor, comparison_error=comparison_error)
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

    # Hard structural invariant (§3.1): an overlapping cue is a shipped bug,
    # not a tolerance band — it fails the run unconditionally, even on the
    # very first v3 run with no prior baseline to compare against.
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

    print(
        f"[harness] CER_thai={agg.cer_thai:.4f} {_fmt_ci('cer_thai')}  "
        f"WER_latin={agg.wer_latin:.4f} {_fmt_ci('wer_latin')}  "
        f"BER={agg.boundary_error_rate:.4f} {_fmt_ci('boundary_error_rate')}  "
        f"WER={agg.wer:.4f}  "
        f"cue_BER={agg.cue_boundary_error_rate:.4f} {_fmt_ci('cue_boundary_error_rate')}  "
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
    parser.add_argument("--db", default="transcriber.db")
    parser.add_argument("--engine-b", help="Override engine_b for a one-command A/B "
                        "comparison, e.g. --engine-b typhoon_rt (4.2)")
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
    parser.add_argument("--experiment", action="store_true",
                        help="Mark this run as an A/B experiment: gated against the "
                        "production baseline but never recorded AS a baseline. Implied "
                        "by --engine-b / --llm-enabled / --self-ensemble (those override "
                        "config.yaml, so their runs don't describe the production config).")
    args = parser.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    self_ensemble = bool(args.self_ensemble or args.self_ensemble_temp_b is not None
                          or args.self_ensemble_beam_b is not None)
    # Any CLI override means this run measures a config that is NOT config.yaml —
    # its result must not become the production baseline.
    experiment = bool(args.experiment or args.engine_b or args.llm_enabled or self_ensemble)
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
    result = run_harness(cfg, Path(args.db), experiment=experiment,
                         establish_baseline=args.establish_baseline)
    if result is not None and result.status == "unresolved":
        sys.exit(2)
    if result is None or not result.passed:
        sys.exit(1)
