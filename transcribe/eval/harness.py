"""Eval harness — runs a pipeline config over the golden set and records metrics."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from transcribe.db import store
from transcribe.eval.metrics import EvalMetrics, compute_metrics, regressed

_GOLDENSET = Path(__file__).parent / "goldenset"


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


def _load_goldenset() -> list[tuple[Path, list[dict]]]:
    """Return [(audio_path, ref_tokens), ...] for every sample in the golden set."""
    samples = []
    for gt_file in sorted(_GOLDENSET.glob("*.json")):
        audio_candidates = [
            gt_file.with_suffix(ext) for ext in (".wav", ".mp3", ".flac", ".m4a")
        ]
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
) -> EvalMetrics:
    """
    Run the golden set through the pipeline and compute aggregate metrics.

    Args:
        config: dict with at least {"engine_a": str, "engine_b": str, ...}
        db_path: path to the SQLite database
        pipeline_fn: callable(audio_path, config) -> list[dict{"text","script"}]
                     If None, the real pipeline is used (imports pipeline.run).
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
        def pipeline_fn(audio_path, cfg):
            return pipeline_run.run_file(str(audio_path), cfg, scratch_db)

    samples = _load_goldenset()
    if not samples:
        print("[harness] WARNING: goldenset is empty — add audio+json pairs to eval/goldenset/")

    tol = float(config.get("boundary_tol_ms", 300.0))

    # Numerators are weighted by the reference size of each signal so per-sample
    # rates aggregate into a corpus-level rate.
    cer_num = wer_lat_num = wer_num = ber_num = 0.0
    total_thai = total_latin = total_words = total_switches = 0

    for audio_path, ref_tokens in samples:
        hyp_tokens = pipeline_fn(audio_path, config)
        # Pass config so reference and hypothesis are normalized identically.
        m = compute_metrics(ref_tokens, hyp_tokens, config=config, boundary_tol_ms=tol)
        cer_num     += m.cer_thai * m.thai_chars
        wer_lat_num += m.wer_latin * m.latin_words
        wer_num     += m.wer * m.total_words
        ber_num     += m.boundary_error_rate * m.ref_switches
        total_thai     += m.thai_chars
        total_latin    += m.latin_words
        total_words    += m.total_words
        total_switches += m.ref_switches

    if scratch_dir is not None:
        shutil.rmtree(scratch_dir, ignore_errors=True)

    agg = EvalMetrics(
        cer_thai=cer_num / total_thai if total_thai else 0.0,
        wer_latin=wer_lat_num / total_latin if total_latin else 0.0,
        boundary_error_rate=ber_num / total_switches if total_switches else 0.0,
        wer=wer_num / total_words if total_words else 0.0,
        thai_chars=total_thai,
        latin_words=total_latin,
        total_words=total_words,
        ref_switches=total_switches,
    )

    conn = store.connect(db_path)
    cfg_hash = _config_hash(config)

    tol_frac = 1.0 + float(config.get("regression_tolerance", 0.02))
    abs_floor = float(config.get("regression_abs_floor", 0.005))
    last = store.get_last_passing_eval(conn)
    passed = True
    if last is not None:
        regressions = []
        if regressed(agg.cer_thai, last.cer_thai, tol_frac, abs_floor):
            regressions.append(f"CER_thai {agg.cer_thai:.4f} vs {last.cer_thai:.4f}")
        if regressed(agg.wer_latin, last.wer_latin, tol_frac, abs_floor):
            regressions.append(f"WER_latin {agg.wer_latin:.4f} vs {last.wer_latin:.4f}")
        if regressed(agg.boundary_error_rate, last.boundary_error_rate, tol_frac, abs_floor):
            regressions.append(
                f"BER {agg.boundary_error_rate:.4f} vs {last.boundary_error_rate:.4f}"
            )
        if regressions:
            passed = False
            print("[harness] REGRESSION: " + "; ".join(regressions))

    store.create_eval_run(
        conn, cfg_hash, agg.wer, agg.boundary_error_rate,
        passed, cer_thai=agg.cer_thai, wer_latin=agg.wer_latin,
        pipeline_version=_pipeline_version(),
        engine_pair=f"{config.get('engine_a', '?')}+{config.get('engine_b', '?')}",
        bias_hash=_bias_hash(conn),
    )
    conn.close()

    print(
        f"[harness] CER_thai={agg.cer_thai:.4f}  WER_latin={agg.wer_latin:.4f}  "
        f"BER={agg.boundary_error_rate:.4f}  WER={agg.wer:.4f}  "
        f"thai_chars={total_thai}  latin_words={total_latin}  "
        f"switches={total_switches}  passed={passed}"
    )
    return agg


if __name__ == "__main__":
    import argparse, yaml
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--db", default="transcriber.db")
    args = parser.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    run_harness(cfg, Path(args.db))
