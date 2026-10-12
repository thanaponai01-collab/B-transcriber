"""One transcription entry point for every tool (CLI, editor, Rough Cut, helper/ClubFriday, MCP).

Wraps `pipeline.run.run_file_job`; it does not replace it (the harness and make_gold keep
calling `run_file`). What it adds: the shared store (`store.resolve_db_path`), the sha256
transcript cache, and a `Transcript` that carries its `job_id`. Because every caller opens the
same database, a bias term or correction saved by one tool reaches the next tool's
`EngineInput`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

from transcribe.db import store
from transcribe.pipeline import coverage
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


# Decode statistics that mark a cue for review (faster-whisper's own thresholds are
# avg_logprob -1.0, no_speech 0.6, compression 2.4; those segments are retried at decode
# time, so the review thresholds sit just inside them).
_LOW_LOGPROB, _HIGH_NO_SPEECH, _HIGH_COMPRESSION = -0.8, 0.4, 2.2


def review_flags(cues: list[dict], segments: list[dict]) -> list[dict]:
    """Cues worth a human listen, most suspicious first.

    Reasons come from `review.suspicion_reasons` (timing, density, word confidence,
    unfamiliar Thai) plus the decode statistics of the segment(s) each cue sits in.
    Flags are priorities, not proof of error."""
    from transcribe import review

    flags = []
    for i, cue in enumerate(cues):
        reasons = review.suspicion_reasons(cue)
        hit = [g for g in segments if g["start_ms"] < cue["end_ms"] and g["end_ms"] > cue["start_ms"]]
        if any(g["avg_logprob"] < _LOW_LOGPROB for g in hit):
            reasons.append("low decode log-probability")
        if any(g["no_speech_prob"] > _HIGH_NO_SPEECH for g in hit):
            reasons.append("possible non-speech")
        if any(g["compression_ratio"] > _HIGH_COMPRESSION for g in hit):
            reasons.append("repetitive text")
        if reasons:
            flags.append({"cue_index": i, "start_ms": cue["start_ms"], "end_ms": cue["end_ms"],
                          "reasons": reasons})
    return sorted(flags, key=lambda f: (-len(f["reasons"]), f["start_ms"]))


def _finish(conn, job_id: int, cues: list[dict]) -> tuple[list, list]:
    """(coverage_gaps, review_flags) for a stored job; read-only, no GPU."""
    speech = [(s.start_ms, s.end_ms) for s in store.get_speech_spans(conn, job_id)
              if s.kind == "speech"]
    gaps = [g.to_dict() for g in coverage.find_gaps(speech, cues)]
    stored = store.get_engine_result(conn, job_id, "a")
    segments = json.loads(stored.raw_segments_json) if stored and stored.raw_segments_json else []
    return gaps, review_flags(cues, segments)


def _model_id(config: dict, engine_name: str) -> str:
    return str(((config.get("engines") or {}).get(engine_name) or {}).get("model_id", ""))


def transcribe(media_path, *, config: dict, db_path: Path | None = None,
               ingest_result=None, glossary=()) -> Transcript:
    """Transcribe `media_path` against the shared store.

    `glossary`: job-specific terms (show title, names, brands) passed to the decoder. A
    glossary changes the decode, so it skips the cache.

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
        cached = (None if glossary else
                  store.find_finished_job(conn, media_id, engine_a, engine_b, PIPELINE_VERSION))
        if cached is not None:
            cues = [{"idx": t.idx, "text": t.text, "start_ms": t.start_ms, "end_ms": t.end_ms,
                     "script": t.script, "confidence": t.confidence,
                     "source_engine": t.source_engine}
                    for t in store.get_tokens(conn, cached.id)]
            gaps, flags = _finish(conn, cached.id, cues)
            return Transcript(cached.id, cues, words_for_job(conn, cached.id), engine_a,
                              _model_id(config, engine_a), PIPELINE_VERSION, cached=True,
                              coverage_gaps=gaps, review_flags=flags)
    finally:
        conn.close()

    job_id, cues = pipeline_run.run_file_job(media_path, config, db_path, ingest_result,
                                           glossary=glossary)
    conn = store.connect(db_path)
    try:
        words = words_for_job(conn, job_id)
        gaps, flags = _finish(conn, job_id, cues)
    finally:
        conn.close()
    return Transcript(job_id, cues, words, engine_a, _model_id(config, engine_a),
                      PIPELINE_VERSION, coverage_gaps=gaps, review_flags=flags)
