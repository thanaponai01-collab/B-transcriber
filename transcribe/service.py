"""One transcription entry point for every tool (CLI, editor, Rough Cut, helper/ClubFriday, MCP).

Wraps `pipeline.run.run_file_job`; it does not replace it (the harness and make_gold keep
calling `run_file`). What it adds: the shared store (`store.resolve_db_path`), the sha256
transcript cache, and a `Transcript` that carries its `job_id`. Because every caller opens the
same database, a bias term or correction saved by one tool reaches the next tool's
`EngineInput`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from transcribe.db import store
from transcribe.pipeline import plan as planning
from transcribe.pipeline import run as pipeline_run
from transcribe.pipeline.run import PIPELINE_VERSION


@dataclass
class Transcript:
    job_id: int
    cues: list[dict]
    words: list
    engine_name: str
    model_id: str
    pipeline_version: str
    cached: bool = False
    coverage_gaps: list = field(default_factory=list)
    review_flags: list = field(default_factory=list)


def _model_id(config: dict, engine_name: str) -> str:
    return str(((config.get("engines") or {}).get(engine_name) or {}).get("model_id", ""))


def transcribe(media_path, *, config: dict, db_path: Path | None = None,
               ingest_result=None) -> Transcript:
    """Transcribe `media_path` against the shared store.

    A finished job for the same media sha256, engine pair and pipeline version is reused
    (zero ASR passes). `db_path` overrides the shared store for scratch databases only.
    """
    from cutdeck.words import words_for_job

    media_path = str(media_path)
    db_path = Path(db_path) if db_path else store.resolve_db_path(config)
    engine_a, engine_b = planning.canonical_engine_names(config)

    store.init_db(db_path)
    conn = store.connect(db_path)
    try:
        media_id = store.create_media(conn, media_path)
        cached = store.find_finished_job(conn, media_id, engine_a, engine_b, PIPELINE_VERSION)
        if cached is not None:
            cues = [{"idx": t.idx, "text": t.text, "start_ms": t.start_ms, "end_ms": t.end_ms,
                     "script": t.script, "confidence": t.confidence,
                     "source_engine": t.source_engine}
                    for t in store.get_tokens(conn, cached.id)]
            return Transcript(cached.id, cues, words_for_job(conn, cached.id), engine_a,
                              _model_id(config, engine_a), PIPELINE_VERSION, cached=True)
    finally:
        conn.close()

    job_id, cues = pipeline_run.run_file_job(media_path, config, db_path, ingest_result)
    conn = store.connect(db_path)
    try:
        words = words_for_job(conn, job_id)
    finally:
        conn.close()
    return Transcript(job_id, cues, words, engine_a, _model_id(config, engine_a),
                      PIPELINE_VERSION)
