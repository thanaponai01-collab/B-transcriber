"""Re-time a stored transcript's words with word_align, without running ASR again.

A transcript stored before word_align ran (or before its current knobs) holds Engine A's own
word times, which sit within one frame of the sound on 13% of heldout edges against 78% after
CTC + snap (transcribe/eval/judge/TRIALS.md, options table). This runs only the CTC step on the
job's stored words and writes them back to the same job: text, cues and corrections are left
as they are. One model on the GPU: don't run it while a transcribe job is running.

    python -m transcribe.retime "path/to/source.mp4"      # the file's latest transcript
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from types import SimpleNamespace

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent


def aligned(raw_words: list[dict]) -> bool:
    """Were these stored words placed by word_align (it records ``start_by`` on each)?"""
    return bool(raw_words) and all("start_by" in w for w in raw_words)


def retime(media_path: str, config: dict, db_path: Path | None = None, force: bool = False) -> dict:
    import torch
    from transcribe.db import store
    from transcribe.pipeline import ingest, word_align
    db_path = Path(db_path) if db_path else store.resolve_db_path(config)
    cfg = config.get("word_align") or {}
    conn = store.connect(db_path)
    try:
        job = store.latest_transcript_job(conn, store.sha256_of_file(media_path))
        if job is None:
            raise SystemExit(f"{media_path} has no transcript: run transcribe(media_path) first")
        result = store.get_engine_result(conn, job.id, "a")
        words = json.loads(result.raw_words_json) if result and result.raw_words_json else []
        if not words:
            raise SystemExit(f"job {job.id} stored no word times to re-time")
        if aligned(words) and not force:
            return {"job": job.id, "words": len(words), "retimed": False}
        cues = [SimpleNamespace(start_ms=t.start_ms, end_ms=t.end_ms) for t in store.get_tokens(conn, job.id)]
        audio, sr = ingest.load_audio(media_path)
        new = word_align.align_words(words, cues, audio, sr, "cuda" if torch.cuda.is_available() else "cpu", cfg)
        store.save_engine_result(conn, job.id, "a", result.engine_name, result.tokens_json,
                                 result.timestamps_final, json.dumps(new, ensure_ascii=False))
    finally:
        conn.close()
    return {"job": job.id, "words": len(new), "retimed": True,
            "starts_moved": sum(o["start_ms"] != n["start_ms"] for o, n in zip(words, new))}


def main(argv: list[str] | None = None) -> int:
    import yaml
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("media", nargs="+")
    p.add_argument("--force", action="store_true", help="re-time words word_align already placed")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    config = yaml.safe_load((ROOT / "transcribe" / "config.yaml").read_text(encoding="utf-8"))
    for media in args.media:
        print(json.dumps({"media": media, **retime(media, config, force=args.force)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
