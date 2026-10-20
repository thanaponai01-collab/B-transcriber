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


def _is_repetitive(text: str) -> bool:
    import zlib
    b = text.encode("utf-8")
    if b:
        compressed = zlib.compress(b)
        if compressed and len(b) / len(compressed) > _HIGH_COMPRESSION:
            return True

    tokens = text.split()
    if len(tokens) >= 3:
        for j in range(len(tokens) - 2):
            if tokens[j] == tokens[j + 1] == tokens[j + 2] and tokens[j] != "ๆ":
                return True
        from collections import Counter
        counts = Counter(tokens)
        for tok, count in counts.items():
            if count >= 3 and tok != "ๆ" and len(tokens) <= 10:
                return True

    import re
    if re.search(r"([ก-๛a-zA-Z0-9]{2,})\s*(?:\1\s*){2,}", text):
        return True

    return False


def _words_for_cue(cue: dict, words: list) -> list[str]:
    c_start, c_end = cue["start_ms"], cue["end_ms"]
    cue_words = []
    for w in words:
        w_text = getattr(w, "text", None) or (w.get("text") if isinstance(w, dict) else None)
        w_start = getattr(w, "start_ms", None) or (w.get("start_ms") if isinstance(w, dict) else None)
        w_end = getattr(w, "end_ms", None) or (w.get("end_ms") if isinstance(w, dict) else None)
        if w_text is None or w_start is None or w_end is None:
            continue
        mid = (w_start + w_end) / 2
        if c_start <= mid < c_end:
            cue_words.append(w_text)
    return cue_words


def review_flags(cues: list[dict], segments: list[dict], words: list | None = None) -> list[dict]:
    """Cues worth a human listen, most suspicious first.

    Reasons come from `review.suspicion_reasons` (timing, density, word confidence,
    unfamiliar Thai) plus the decode statistics of the segment(s) each cue sits in.
    Flags are priorities, not proof of error."""
    from transcribe import review

    flags = []
    for i, cue in enumerate(cues):
        cue_words = _words_for_cue(cue, words) if words else None
        reasons = review.suspicion_reasons(cue, words=cue_words)
        hit = [g for g in segments if g["start_ms"] < cue["end_ms"] and g["end_ms"] > cue["start_ms"]]
        if any(g["avg_logprob"] < _LOW_LOGPROB for g in hit):
            reasons.append("low decode log-probability")
        if any(g["no_speech_prob"] > _HIGH_NO_SPEECH for g in hit):
            reasons.append("possible non-speech")
        if any(g["compression_ratio"] > _HIGH_COMPRESSION for g in hit):
            is_rep = _is_repetitive(cue["text"]) or (
                (i > 0 and cue["text"] == cues[i - 1]["text"]) or
                (i + 1 < len(cues) and cue["text"] == cues[i + 1]["text"])
            )
            if is_rep:
                reasons.append("repetitive text")
        elif _is_repetitive(cue["text"]):
            reasons.append("repetitive text")

        if reasons:
            flags.append({"cue_index": i, "start_ms": cue["start_ms"], "end_ms": cue["end_ms"],
                          "reasons": reasons})
    return sorted(flags, key=lambda f: (-len(f["reasons"]), f["start_ms"]))


def _finish(conn, job_id: int, cues: list[dict], words: list | None = None) -> tuple[list, list]:
    """(coverage_gaps, review_flags) for a stored job; read-only, no GPU."""
    speech = [(s.start_ms, s.end_ms) for s in store.get_speech_spans(conn, job_id)
              if s.kind == "speech"]
    gaps = [g.to_dict() for g in coverage.find_gaps(speech, cues)]
    stored = store.get_engine_result(conn, job_id, "a")
    segments = json.loads(stored.raw_segments_json) if stored and stored.raw_segments_json else []
    return gaps, review_flags(cues, segments, words=words)


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
    media_sha256 = store.sha256_of_file(media_path)
    conn = store.connect(db_path)
    try:
        media_id = store.create_media(conn, media_path, sha256=media_sha256)
        cached = None
        if not glossary:
            bias_terms = store.get_bias_term_strings(conn)
            bias_weights = store.get_bias_term_weights(conn)
            rf = planning.resume_fingerprint(config, bias_terms, bias_weights)
            cached = store.find_finished_job(
                conn, media_id, engine_a, engine_b, PIPELINE_VERSION, rf
            )
        if cached is not None:
            cues = [{"idx": t.idx, "text": t.text, "start_ms": t.start_ms, "end_ms": t.end_ms,
                     "script": t.script, "confidence": t.confidence,
                     "source_engine": t.source_engine}
                    for t in store.get_tokens(conn, cached.id)]
            cached_words = words_for_job(conn, cached.id)
            gaps, flags = _finish(conn, cached.id, cues, words=cached_words)
            return Transcript(cached.id, cues, cached_words, engine_a,
                              _model_id(config, engine_a), PIPELINE_VERSION, cached=True,
                              coverage_gaps=gaps, review_flags=flags)
    finally:
        conn.close()

    try:
        job_id, cues = pipeline_run.run_file_job(media_path, config, db_path, ingest_result,
                                                 glossary=glossary, sha256=media_sha256)
    except TypeError:
        job_id, cues = pipeline_run.run_file_job(media_path, config, db_path, ingest_result,
                                                 glossary=glossary)
    conn = store.connect(db_path)
    try:
        words = words_for_job(conn, job_id)
        gaps, flags = _finish(conn, job_id, cues, words=words)
    finally:
        conn.close()
    return Transcript(job_id, cues, words, engine_a, _model_id(config, engine_a),
                      PIPELINE_VERSION, coverage_gaps=gaps, review_flags=flags)
