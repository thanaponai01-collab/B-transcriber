"""Eval harness — runs a pipeline config over the golden set and records metrics."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import NamedTuple

from transcribe.db import store
from transcribe.eval.metrics import (
    CI_METRICS, EvalMetrics, boundary_f1_error, bootstrap_ci, compute_metrics, regressed,
)
from transcribe.thai.atoms import default_lexicon
from transcribe.thai.lint import find_cue_legality_violations

_GOLDENSET = Path(__file__).parent / "goldenset"


def _safe_print(msg: str) -> None:
    """print(), tolerant of a Windows console's non-UTF8 code page (cp1252)
    choking on Thai text in a cue-legality violation's detail — never let a
    console-encoding limitation crash the harness run itself."""
    try:
        print(msg)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "utf-8"
        print(msg.encode(enc, errors="replace").decode(enc))

# Printed/stored label for each gated metric (matches the pre-Phase-A print format).
_GATE_LABELS = {
    "cer_thai": "CER_thai",
    "wer_latin": "WER_latin",
    "boundary_error_rate": "BER",
    "cue_boundary_error_rate": "cue_BER",
}


class HarnessResult(NamedTuple):
    """The harness is the single gate authority: it captures the prior passing
    baseline *before* writing the new eval_run, gates on all three primary
    signals, and returns its verdict. Callers must consume `passed` — never
    re-read get_last_passing_eval (that would compare the new run against itself)."""
    metrics: EvalMetrics
    passed: bool
    baseline: EvalMetrics | None
    rtf: float | None = None
    ci: dict[str, tuple[float, float]] | None = None
    unresolved: list[str] | None = None


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


def run_harness(
    config: dict,
    db_path: Path,
    pipeline_fn=None,
    experiment: bool = False,
) -> HarnessResult | None:
    """
    Run the golden set through the pipeline and compute aggregate metrics.

    Args:
        config: dict with at least {"engine_a": str, "engine_b": str, ...}
        db_path: path to the SQLite database
        pipeline_fn: callable(audio_path, config) -> list[dict{"text","script"}]
                     If None, the real pipeline is used (imports pipeline.run).
        experiment: True for an A/B probe (e.g. `--engine-b X`, `--llm-enabled`).
                    The run is still gated against the production baseline, but
                    its eval_run row is marked is_experiment=1 so it can never
                    BECOME the baseline a later production run is compared to.
                    Production config changes (engine swap in config.yaml, bias
                    promotion) stay experiment=False — the gate must compare
                    them against the previous production baseline and, on pass,
                    they legitimately become the new one.
    Returns:
        EvalMetrics aggregate over all golden samples.
    """
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

    # Numerators are weighted by the reference size of each signal so per-sample
    # rates aggregate into a corpus-level rate. BER instead aggregates by
    # micro-F1 (summed matched/ref/hyp switch counts, one F1 at the end) — a
    # ref-weighted mean would zero out samples with no reference switches, so
    # switches hallucinated on monolingual clips would never be penalized.
    cer_num = wer_lat_num = wer_num = 0.0
    total_thai = total_latin = total_words = 0
    total_switches = total_hyp_switches = total_matched = 0
    total_ref_cues = total_hyp_cues = total_matched_cues = 0
    total_overlapping_cues = total_cue_count_delta = total_nonzero_gaps = 0
    global_shortest_cue_ms: float | None = None
    clip_metrics: list[EvalMetrics] = []
    total_wall_s = 0.0
    total_audio_s = 0.0
    # Phase 3 cue-legality lint (HANDOFF_THAI_BREAK_ATOMS.md §5): shares the
    # splitter's own BreakLexicon so the lint can never drift from what
    # glue_atoms actually protects.
    lexicon = default_lexicon(config)
    total_hyp_lint_violations = 0
    total_ref_lint_violations = 0

    for audio_path, ref_tokens in samples:
        t0 = time.perf_counter()
        hyp_tokens = pipeline_fn(audio_path, config)
        total_wall_s += time.perf_counter() - t0
        total_audio_s += _audio_duration_s(audio_path)
        # Pass config so reference and hypothesis are normalized identically.
        m = compute_metrics(ref_tokens, hyp_tokens, config=config, boundary_tol_ms=tol)
        clip_metrics.append(m)

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
        cer_num     += m.cer_thai * m.thai_chars
        wer_lat_num += m.wer_latin * m.latin_words
        wer_num     += m.wer * m.total_words
        total_thai     += m.thai_chars
        total_latin    += m.latin_words
        total_words    += m.total_words
        total_switches     += m.ref_switches
        total_hyp_switches += m.hyp_switches
        total_matched      += m.matched_switches
        total_ref_cues        += m.ref_cues
        total_hyp_cues        += m.hyp_cues
        total_matched_cues    += m.matched_cues
        total_overlapping_cues += m.overlapping_cues
        total_cue_count_delta  += m.cue_count_delta
        total_nonzero_gaps     += m.nonzero_gap_count
        if m.shortest_cue_ms is not None and (
            global_shortest_cue_ms is None or m.shortest_cue_ms < global_shortest_cue_ms
        ):
            global_shortest_cue_ms = m.shortest_cue_ms

    if scratch_dir is not None:
        shutil.rmtree(scratch_dir, ignore_errors=True)

    agg = EvalMetrics(
        cer_thai=cer_num / total_thai if total_thai else 0.0,
        wer_latin=wer_lat_num / total_latin if total_latin else 0.0,
        boundary_error_rate=boundary_f1_error(
            total_matched, total_switches, total_hyp_switches),
        wer=wer_num / total_words if total_words else 0.0,
        thai_chars=total_thai,
        latin_words=total_latin,
        total_words=total_words,
        ref_switches=total_switches,
        hyp_switches=total_hyp_switches,
        matched_switches=total_matched,
        cue_boundary_error_rate=boundary_f1_error(
            total_matched_cues, total_ref_cues, total_hyp_cues),
        ref_cues=total_ref_cues,
        hyp_cues=total_hyp_cues,
        matched_cues=total_matched_cues,
        overlapping_cues=total_overlapping_cues,
        cue_count_delta=total_cue_count_delta,
        shortest_cue_ms=global_shortest_cue_ms,
        nonzero_gap_count=total_nonzero_gaps,
    )

    conn = store.connect(db_path)
    cfg_hash = _config_hash(config)

    # Bootstrap CIs (Phase A, HANDOFF_ONE_ENGINE §3.1): resample clips, not
    # just report a point estimate. n_draws=1000 is cheap at this corpus size
    # (thousands of clip-count-sized resamples, no re-transcription involved).
    ci_bounds = {name: bootstrap_ci(clip_metrics, name) for name in CI_METRICS}
    rtf = total_wall_s / total_audio_s if total_audio_s > 0 else None

    tol_frac = 1.0 + float(config.get("regression_tolerance", 0.02))
    abs_floor = float(config.get("regression_abs_floor", 0.005))
    last = store.get_last_passing_eval(conn)
    passed = True
    regressions: list[str] = []
    unresolved: list[str] = []
    unresolved_names: list[str] = []
    if last is not None:
        for name in CI_METRICS:
            now, base = getattr(agg, name), getattr(last, name)
            if not regressed(now, base, tol_frac, abs_floor):
                continue
            label = _GATE_LABELS[name]
            ci_lo, ci_hi = ci_bounds[name]
            if ci_lo <= base <= ci_hi:
                # Point estimate crossed the tolerance band, but this run's
                # own bootstrap CI still contains the baseline value — not
                # distinguishable from run-to-run resampling noise at this
                # corpus size. Record it; don't hard-fail on it (§3.1 rule 1).
                unresolved.append(
                    f"{label} {now:.4f} vs {base:.4f} (baseline within 95% CI "
                    f"[{ci_lo:.4f}, {ci_hi:.4f}] - unresolved, needs more data)"
                )
                unresolved_names.append(name)
            else:
                passed = False
                regressions.append(f"{label} {now:.4f} vs {base:.4f}")
        if regressions:
            print("[harness] REGRESSION: " + "; ".join(regressions))
        if unresolved:
            print("[harness] UNRESOLVED (within CI, not a confirmed regression): "
                  + "; ".join(unresolved))

    # Hard structural invariant (§3.1): an overlapping cue is a shipped bug,
    # not a tolerance band — it fails the run unconditionally, even on the
    # very first v3 run with no prior baseline to compare against.
    if agg.overlapping_cues > 0:
        passed = False
        print(f"[harness] HARD FAIL: {agg.overlapping_cues} overlapping cue(s) in hypothesis output")

    gate_unresolved_names = ",".join(unresolved_names) or None

    store.create_eval_run(
        conn, cfg_hash, agg.wer, agg.boundary_error_rate,
        passed, cer_thai=agg.cer_thai, wer_latin=agg.wer_latin,
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
    )
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
        f"thai_chars={total_thai}  latin_words={total_latin}  "
        f"switches={total_switches} (hyp {total_hyp_switches}, matched {total_matched})  "
        f"passed={passed}"
    )
    return HarnessResult(metrics=agg, passed=passed, baseline=last,
                          rtf=rtf, ci=ci_bounds, unresolved=unresolved or None)


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
    result = run_harness(cfg, Path(args.db), experiment=experiment)
    if result is None or not result.passed:
        sys.exit(1)
