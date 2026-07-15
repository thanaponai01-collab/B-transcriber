"""Learn from a fully hand-corrected final .srt (e.g. re-timed/re-cut in an
NLE like Premiere Pro) — the flywheel counterpart to the web editor's /save
endpoint, for edits that broke idx-based correspondence.

Usage:
    python scripts/learn_from_srt.py <job_id> <final.srt> [--db transcriber.db]
                                      [--config transcribe/config.yaml]
                                      [--yes] [--no-promote]

Flow: load the job's original tokens -> time-align them against the final
SRT's cues -> print a match/mismatch summary -> require confirmation (or
--yes) before writing anything -> write correction rows -> (unless
--no-promote) run the bias-index promotion + regression gate, same as the
web editor path is meant to trigger.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from transcribe.db import store
from transcribe.flywheel import biasindex
from transcribe.flywheel.align_srt import TimebaseMismatch, align_tokens_to_cues, write_corrections
from transcribe.srt_io import parse_srt

_MAX_SAMPLE_DIFFS = 5
_MAX_UNMATCHED_PREVIEW = 5


def _print_summary(result, job_id: int) -> None:
    s = result.summary
    print(f"[learn_from_srt] job {job_id}: "
          f"{s.matched_original} original token(s) matched, "
          f"{s.matched_final} final cue(s) matched, "
          f"{s.unmatched_original} deletion(s) (original with no final cue), "
          f"{s.unmatched_final} insertion(s) (final cue with no source token, skipped)")
    if s.unmatched_final_texts:
        preview = s.unmatched_final_texts[:_MAX_UNMATCHED_PREVIEW]
        more = len(s.unmatched_final_texts) - len(preview)
        suffix = f" (+{more} more)" if more > 0 else ""
        print(f"[learn_from_srt] skipped insertions: {preview}{suffix}")
    print(f"[learn_from_srt] {len(result.pairs)} correction(s) will be written:")
    for pair in result.pairs[:_MAX_SAMPLE_DIFFS]:
        print(f"    idx={pair.token_idx}: {pair.raw_text!r} -> {pair.corrected_text!r}")
    if len(result.pairs) > _MAX_SAMPLE_DIFFS:
        print(f"    ... and {len(result.pairs) - _MAX_SAMPLE_DIFFS} more")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id", type=int)
    parser.add_argument("srt_path")
    parser.add_argument("--db", default=str(ROOT / "transcriber.db"))
    parser.add_argument("--config", default=str(ROOT / "transcribe" / "config.yaml"))
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    parser.add_argument("--no-promote", action="store_true",
                         help="write corrections only — skip update_bias_index/regression gate")
    args = parser.parse_args()

    conn = store.connect(Path(args.db))
    tokens = store.get_tokens(conn, args.job_id)
    if not tokens:
        conn.close()
        raise SystemExit(f"No tokens found for job {args.job_id}")

    original = [
        {"idx": t.idx, "text": t.text, "start_ms": t.start_ms, "end_ms": t.end_ms,
         "source_engine": t.source_engine}
        for t in tokens
    ]
    final_cues = parse_srt(Path(args.srt_path).read_text(encoding="utf-8-sig"))
    if not final_cues:
        conn.close()
        raise SystemExit(f"No cues parsed from {args.srt_path}")

    try:
        result = align_tokens_to_cues(original, final_cues)
    except TimebaseMismatch as e:
        conn.close()
        raise SystemExit(f"[learn_from_srt] refusing to align: {e}")

    _print_summary(result, args.job_id)

    if not result.pairs:
        print("[learn_from_srt] nothing to write — no text changed.")
        conn.close()
        return

    if not args.yes:
        reply = input("Write these corrections? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("[learn_from_srt] aborted — no changes written.")
            conn.close()
            return

    n_written = write_corrections(conn, args.job_id, result.pairs)
    print(f"[learn_from_srt] wrote {n_written} correction row(s).")

    if args.no_promote:
        conn.close()
        return

    import yaml
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    active_engines = [config.get("engine_a"), config.get("engine_b")]
    try:
        terms = biasindex.update_bias_index(
            conn, active_engines=active_engines, eval_config=config,
            db_path=Path(args.db), run_regression_gate=True,
        )
        print(f"[learn_from_srt] bias index updated — {len(terms)} active term(s).")
    except RuntimeError as e:
        print(f"[learn_from_srt] bias promotion BLOCKED: {e}")
        conn.close()
        raise SystemExit(1)

    conn.close()


if __name__ == "__main__":
    main()
