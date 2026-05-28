"""Eval harness — runs a pipeline config over the golden set and records metrics."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from transcribe.db import store
from transcribe.eval.metrics import EvalMetrics, compute_metrics

_GOLDENSET = Path(__file__).parent / "goldenset"


def _config_hash(config: dict) -> str:
    blob = json.dumps(config, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


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
    if pipeline_fn is None:
        from transcribe.pipeline import run as pipeline_run
        def pipeline_fn(audio_path, cfg):
            return pipeline_run.run_file(str(audio_path), cfg, db_path)

    samples = _load_goldenset()
    if not samples:
        print("[harness] WARNING: goldenset is empty — add audio+json pairs to eval/goldenset/")

    total_wer_num = 0.0
    total_ber_num = 0.0
    total_ref = 0
    total_boundary = 0

    for audio_path, ref_tokens in samples:
        hyp_tokens = pipeline_fn(audio_path, config)
        m = compute_metrics(ref_tokens, hyp_tokens)
        total_wer_num += m.wer * m.total_words
        total_ber_num += m.boundary_error_rate * m.boundary_words
        total_ref += m.total_words
        total_boundary += m.boundary_words

    agg_wer = total_wer_num / total_ref if total_ref else 0.0
    agg_ber = total_ber_num / total_boundary if total_boundary else 0.0

    agg = EvalMetrics(
        wer=agg_wer,
        boundary_error_rate=agg_ber,
        total_words=total_ref,
        boundary_words=total_boundary,
    )

    conn = store.connect(db_path)
    cfg_hash = _config_hash(config)

    last = store.get_last_passing_eval(conn)
    passed = True
    if last is not None:
        if agg.wer > last.wer * 1.02 or agg.boundary_error_rate > last.boundary_error_rate * 1.02:
            passed = False
            print(
                f"[harness] REGRESSION: WER {agg.wer:.4f} vs last {last.wer:.4f}, "
                f"BER {agg.boundary_error_rate:.4f} vs last {last.boundary_error_rate:.4f}"
            )

    store.create_eval_run(conn, cfg_hash, agg.wer, agg.boundary_error_rate, passed)
    conn.close()

    print(
        f"[harness] WER={agg.wer:.4f}  BER={agg.boundary_error_rate:.4f}  "
        f"words={total_ref}  boundary_words={total_boundary}  passed={passed}"
    )
    return agg


if __name__ == "__main__":
    import argparse, yaml
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--db", default="transcriber.db")
    args = parser.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    run_harness(cfg, Path(args.db))
