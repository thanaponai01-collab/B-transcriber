"""All database access. No raw SQL outside this module."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_SCHEMA = Path(__file__).parent / "schema.sql"
_DEFAULT_DB = Path(__file__).parent.parent.parent / "transcriber.db"


def connect(db_path: Path = _DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path = _DEFAULT_DB) -> None:
    conn = connect(db_path)
    conn.executescript(_SCHEMA.read_text(encoding="utf-8"))
    _migrate(conn)
    conn.commit()
    conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Idempotent column additions for tables created before a schema bump.

    CREATE TABLE IF NOT EXISTS never alters an existing table, so new columns
    must be added explicitly for pre-existing databases. (New *tables* like
    speech_span are created by re-running schema.sql in init_db.)"""
    def _add(table: str, column: str, ddl: str) -> None:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

    # eval_run signals + attribution (A.2)
    _add("eval_run", "cer_thai", "cer_thai REAL NOT NULL DEFAULT 1.0")
    _add("eval_run", "wer_latin", "wer_latin REAL NOT NULL DEFAULT 1.0")
    _add("eval_run", "kind", "kind TEXT NOT NULL DEFAULT 'transcribe'")
    _add("eval_run", "pipeline_version", "pipeline_version TEXT")
    _add("eval_run", "engine_pair", "engine_pair TEXT")
    _add("eval_run", "bias_hash", "bias_hash TEXT")

    # media timebase (GAP-1/2)
    _add("media", "fps_num", "fps_num INTEGER")
    _add("media", "fps_den", "fps_den INTEGER")
    _add("media", "is_vfr", "is_vfr INTEGER NOT NULL DEFAULT 0")

    # correction reason (GAP-7)
    _add("correction", "reason", "reason TEXT")
    # sub-cue promotable span (5.3)
    _add("correction", "corrected_span", "corrected_span TEXT")

    # job resumability (4.1, GAP-8)
    _add("job", "job_phase", "job_phase TEXT")


# ── dataclasses mirroring schema rows ─────────────────────────────────────────

@dataclass
class MediaRow:
    id: int
    path: str
    duration_ms: Optional[int]
    sha256: str
    fps_num: Optional[int]
    fps_den: Optional[int]
    is_vfr: int
    created_at: str


@dataclass
class JobRow:
    id: int
    media_id: int
    engine_a: str
    engine_b: str
    pipeline_version: str
    created_at: str
    status: str
    job_phase: Optional[str] = None


@dataclass
class TokenRow:
    id: int
    job_id: int
    idx: int
    text: str
    start_ms: int
    end_ms: int
    script: str
    confidence: Optional[float]
    source_engine: str
    speaker_id: Optional[str]


@dataclass
class CorrectionRow:
    id: int
    job_id: int
    token_idx: int
    raw_text: str
    corrected_text: str
    error_type: Optional[str]
    source_engine: str
    reason: Optional[str]
    created_at: str
    corrected_span: Optional[str] = None


@dataclass
class EngineResultRow:
    id: int
    job_id: int
    engine_slot: str
    engine_name: str
    tokens_json: str
    timestamps_final: bool
    raw_words_json: Optional[str]
    created_at: str


@dataclass
class SpeechSpanRow:
    id: int
    job_id: int
    idx: int
    start_ms: int
    end_ms: int
    kind: str


@dataclass
class CutPlanRow:
    id: int
    job_id: int
    plan_version: str
    plan_json: str
    status: str
    created_at: str


@dataclass
class BiasTermRow:
    id: int
    term: str
    term_type: str
    script: Optional[str]
    added_by: str
    weight: float
    created_at: str


@dataclass
class EvalRunRow:
    id: int
    config_hash: str
    wer: float
    boundary_error_rate: float
    cer_thai: float
    wer_latin: float
    kind: str
    pipeline_version: Optional[str]
    engine_pair: Optional[str]
    bias_hash: Optional[str]
    ran_at: str
    passed: bool


# ── media ─────────────────────────────────────────────────────────────────────

def sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def create_media(conn: sqlite3.Connection, path: str, duration_ms: Optional[int] = None) -> int:
    digest = sha256_of_file(path)
    cur = conn.execute(
        "INSERT OR IGNORE INTO media (path, duration_ms, sha256) VALUES (?, ?, ?)",
        (path, duration_ms, digest),
    )
    conn.commit()
    if cur.lastrowid:
        return cur.lastrowid
    row = conn.execute("SELECT id FROM media WHERE sha256 = ?", (digest,)).fetchone()
    return row["id"]


def get_media(conn: sqlite3.Connection, media_id: int) -> Optional[MediaRow]:
    row = conn.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
    if row is None:
        return None
    return MediaRow(**dict(row))


def set_media_timebase(
    conn: sqlite3.Connection,
    media_id: int,
    fps_num: int,
    fps_den: int,
    is_vfr: bool,
) -> None:
    """Persist a probed Timebase (GAP-1/2). fps stored as an integer pair only."""
    conn.execute(
        "UPDATE media SET fps_num = ?, fps_den = ?, is_vfr = ? WHERE id = ?",
        (fps_num, fps_den, int(is_vfr), media_id),
    )
    conn.commit()


# ── job ───────────────────────────────────────────────────────────────────────

def create_job(
    conn: sqlite3.Connection,
    media_id: int,
    engine_a: str,
    engine_b: str,
    pipeline_version: str,
) -> int:
    cur = conn.execute(
        "INSERT INTO job (media_id, engine_a, engine_b, pipeline_version) VALUES (?, ?, ?, ?)",
        (media_id, engine_a, engine_b, pipeline_version),
    )
    conn.commit()
    return cur.lastrowid


def get_job(conn: sqlite3.Connection, job_id: int) -> Optional[JobRow]:
    row = conn.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    return JobRow(**dict(row))


def update_job_status(conn: sqlite3.Connection, job_id: int, status: str) -> None:
    conn.execute("UPDATE job SET status = ? WHERE id = ?", (status, job_id))
    conn.commit()


def list_jobs(conn: sqlite3.Connection) -> list[JobRow]:
    rows = conn.execute("SELECT * FROM job ORDER BY created_at DESC").fetchall()
    return [JobRow(**dict(r)) for r in rows]


def update_job_phase(conn: sqlite3.Connection, job_id: int, phase: str) -> None:
    conn.execute("UPDATE job SET job_phase = ? WHERE id = ?", (phase, job_id))
    conn.commit()


def find_resumable_job(
    conn: sqlite3.Connection,
    media_id: int,
    engine_a: str,
    engine_b: str,
    pipeline_version: str,
) -> Optional[JobRow]:
    """The most recent 'failed' job for this exact (media, engine pair, pipeline
    version) — a crash mid-run leaves state we can resume from (4.1, GAP-8).
    Engine/version must match exactly: swapping an engine invalidates any
    persisted engine_result rows, so that job is not resumable, only re-runnable
    as a fresh job."""
    row = conn.execute(
        "SELECT * FROM job WHERE media_id = ? AND engine_a = ? AND engine_b = ? "
        "AND pipeline_version = ? AND status = 'failed' ORDER BY id DESC LIMIT 1",
        (media_id, engine_a, engine_b, pipeline_version),
    ).fetchone()
    if row is None:
        return None
    return JobRow(**dict(row))


# ── token ─────────────────────────────────────────────────────────────────────

def create_token(
    conn: sqlite3.Connection,
    job_id: int,
    idx: int,
    text: str,
    start_ms: int,
    end_ms: int,
    script: str,
    confidence: Optional[float],
    source_engine: str,
    speaker_id: Optional[str] = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO token (job_id, idx, text, start_ms, end_ms, script, confidence, source_engine, speaker_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (job_id, idx, text, start_ms, end_ms, script, confidence, source_engine, speaker_id),
    )
    return cur.lastrowid


def bulk_create_tokens(conn: sqlite3.Connection, rows: list[dict]) -> None:
    conn.executemany(
        """INSERT INTO token (job_id, idx, text, start_ms, end_ms, script, confidence, source_engine, speaker_id)
           VALUES (:job_id, :idx, :text, :start_ms, :end_ms, :script, :confidence, :source_engine, :speaker_id)""",
        rows,
    )
    conn.commit()


def get_tokens(conn: sqlite3.Connection, job_id: int) -> list[TokenRow]:
    rows = conn.execute("SELECT * FROM token WHERE job_id = ? ORDER BY idx", (job_id,)).fetchall()
    return [TokenRow(**dict(r)) for r in rows]


def delete_tokens(conn: sqlite3.Connection, job_id: int) -> None:
    """Clear a job's tokens before re-writing (idempotent final write on resume, 4.1)."""
    conn.execute("DELETE FROM token WHERE job_id = ?", (job_id,))
    conn.commit()


# ── correction ────────────────────────────────────────────────────────────────

def create_correction(
    conn: sqlite3.Connection,
    job_id: int,
    token_idx: int,
    raw_text: str,
    corrected_text: str,
    source_engine: str,
    error_type: Optional[str] = None,
    reason: Optional[str] = None,
    corrected_span: Optional[str] = None,
) -> int:
    # Latest correction wins per (job, token): a re-save of the same job must
    # replace the earlier row, not stack a duplicate — stacked rows inflate the
    # flywheel's occurrence counts (min_occurrences could be crossed by saving
    # the same edit three times instead of by three independent corrections).
    conn.execute(
        "DELETE FROM correction WHERE job_id = ? AND token_idx = ?",
        (job_id, token_idx),
    )
    cur = conn.execute(
        """INSERT INTO correction
             (job_id, token_idx, raw_text, corrected_text, corrected_span, error_type, source_engine, reason)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (job_id, token_idx, raw_text, corrected_text, corrected_span, error_type, source_engine, reason),
    )
    conn.commit()
    return cur.lastrowid


def delete_correction(conn: sqlite3.Connection, job_id: int, token_idx: int) -> None:
    """Remove the correction for one token (the user reverted it to the raw text)."""
    conn.execute(
        "DELETE FROM correction WHERE job_id = ? AND token_idx = ?",
        (job_id, token_idx),
    )
    conn.commit()


def update_correction_span(conn: sqlite3.Connection, correction_id: int, corrected_span: str) -> None:
    conn.execute(
        "UPDATE correction SET corrected_span = ? WHERE id = ?",
        (corrected_span, correction_id),
    )
    conn.commit()


def get_corrections(conn: sqlite3.Connection, job_id: int) -> list[CorrectionRow]:
    rows = conn.execute(
        "SELECT * FROM correction WHERE job_id = ? ORDER BY token_idx", (job_id,)
    ).fetchall()
    return [CorrectionRow(**dict(r)) for r in rows]


def get_all_corrections(conn: sqlite3.Connection) -> list[CorrectionRow]:
    rows = conn.execute("SELECT * FROM correction ORDER BY created_at").fetchall()
    return [CorrectionRow(**dict(r)) for r in rows]


def get_correction_counts(conn: sqlite3.Connection) -> list[tuple[str, str, int]]:
    """Return (term, source_engine, count) aggregated in SQLite.

    `term` is the minimal promotable span (5.3) — COALESCE so pre-5.3 rows without
    a span fall back to the full corrected cue."""
    rows = conn.execute(
        "SELECT COALESCE(corrected_span, corrected_text) AS term, source_engine, COUNT(*) AS n "
        "FROM correction GROUP BY term, source_engine"
    ).fetchall()
    return [(r["term"], r["source_engine"], r["n"]) for r in rows]


# ── speech_span (VAD master timeline, GAP-3) ──────────────────────────────────

def bulk_create_speech_spans(conn: sqlite3.Connection, job_id: int, spans: list[dict]) -> None:
    """Persist VAD spans for a job. Each span dict: {idx, start_ms, end_ms, kind}."""
    conn.executemany(
        """INSERT INTO speech_span (job_id, idx, start_ms, end_ms, kind)
           VALUES (:job_id, :idx, :start_ms, :end_ms, :kind)""",
        [{"job_id": job_id, **s} for s in spans],
    )
    conn.commit()


def get_speech_spans(conn: sqlite3.Connection, job_id: int) -> list[SpeechSpanRow]:
    rows = conn.execute(
        "SELECT * FROM speech_span WHERE job_id = ? ORDER BY idx", (job_id,)
    ).fetchall()
    return [SpeechSpanRow(**dict(r)) for r in rows]


def delete_speech_spans(conn: sqlite3.Connection, job_id: int) -> None:
    """Clear spans for a job before re-inserting (idempotent re-ingest on resume, 4.1)."""
    conn.execute("DELETE FROM speech_span WHERE job_id = ?", (job_id,))
    conn.commit()


# ── engine_result (4.1/4.2, GAP-8) ────────────────────────────────────────────

def save_engine_result(
    conn: sqlite3.Connection,
    job_id: int,
    engine_slot: str,
    engine_name: str,
    tokens_json: str,
    timestamps_final: bool,
    raw_words_json: Optional[str] = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO engine_result (job_id, engine_slot, engine_name, tokens_json, timestamps_final, raw_words_json)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(job_id, engine_slot) DO UPDATE SET
             engine_name = excluded.engine_name,
             tokens_json = excluded.tokens_json,
             timestamps_final = excluded.timestamps_final,
             raw_words_json = excluded.raw_words_json""",
        (job_id, engine_slot, engine_name, tokens_json, int(timestamps_final), raw_words_json),
    )
    conn.commit()
    if cur.lastrowid:
        return cur.lastrowid
    return conn.execute(
        "SELECT id FROM engine_result WHERE job_id = ? AND engine_slot = ?",
        (job_id, engine_slot),
    ).fetchone()["id"]


def get_engine_result(conn: sqlite3.Connection, job_id: int, engine_slot: str) -> Optional[EngineResultRow]:
    row = conn.execute(
        "SELECT * FROM engine_result WHERE job_id = ? AND engine_slot = ?",
        (job_id, engine_slot),
    ).fetchone()
    if row is None:
        return None
    r = dict(row)
    r["timestamps_final"] = bool(r["timestamps_final"])
    return EngineResultRow(**r)


# ── cut_plan (CutDeck Layer-4 artifact, Part B) ───────────────────────────────

def create_cut_plan(
    conn: sqlite3.Connection,
    job_id: int,
    plan_version: str,
    plan_json: str,
    status: str = "proposed",
) -> int:
    cur = conn.execute(
        "INSERT INTO cut_plan (job_id, plan_version, plan_json, status) VALUES (?, ?, ?, ?)",
        (job_id, plan_version, plan_json, status),
    )
    conn.commit()
    return cur.lastrowid


def get_cut_plan(conn: sqlite3.Connection, plan_id: int) -> Optional[CutPlanRow]:
    row = conn.execute("SELECT * FROM cut_plan WHERE id = ?", (plan_id,)).fetchone()
    if row is None:
        return None
    return CutPlanRow(**dict(row))


def get_cut_plans_for_job(conn: sqlite3.Connection, job_id: int) -> list[CutPlanRow]:
    rows = conn.execute(
        "SELECT * FROM cut_plan WHERE job_id = ? ORDER BY created_at DESC, id DESC", (job_id,)
    ).fetchall()
    return [CutPlanRow(**dict(r)) for r in rows]


def update_cut_plan_status(conn: sqlite3.Connection, plan_id: int, status: str) -> None:
    conn.execute("UPDATE cut_plan SET status = ? WHERE id = ?", (status, plan_id))
    conn.commit()


# ── bias_term ─────────────────────────────────────────────────────────────────

def upsert_bias_term(
    conn: sqlite3.Connection,
    term: str,
    term_type: str,
    script: Optional[str],
    added_by: str,
    weight: float = 1.0,
) -> int:
    cur = conn.execute(
        """INSERT INTO bias_term (term, term_type, script, added_by, weight)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(term) DO UPDATE SET weight = excluded.weight, term_type = excluded.term_type""",
        (term, term_type, script, added_by, weight),
    )
    conn.commit()
    if cur.lastrowid:
        return cur.lastrowid
    return conn.execute("SELECT id FROM bias_term WHERE term = ?", (term,)).fetchone()["id"]


def get_bias_terms(conn: sqlite3.Connection) -> list[BiasTermRow]:
    rows = conn.execute("SELECT * FROM bias_term ORDER BY weight DESC").fetchall()
    return [BiasTermRow(**dict(r)) for r in rows]


def get_bias_term_strings(conn: sqlite3.Connection) -> list[str]:
    return [r.term for r in get_bias_terms(conn)]


def get_bias_term_weights(conn: sqlite3.Connection) -> dict[str, float]:
    """{term: weight} so prompt packing can rank by learned weight, not insertion
    order (5.1)."""
    return {r.term: r.weight for r in get_bias_terms(conn)}


def delete_bias_term(conn: sqlite3.Connection, term: str) -> None:
    conn.execute("DELETE FROM bias_term WHERE term = ?", (term,))
    conn.commit()


# ── eval_run ──────────────────────────────────────────────────────────────────

def create_eval_run(
    conn: sqlite3.Connection,
    config_hash: str,
    wer: float,
    boundary_error_rate: float,
    passed: bool,
    cer_thai: float = 1.0,
    wer_latin: float = 1.0,
    kind: str = "transcribe",
    pipeline_version: Optional[str] = None,
    engine_pair: Optional[str] = None,
    bias_hash: Optional[str] = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO eval_run (config_hash, wer, boundary_error_rate, cer_thai, wer_latin, "
        "kind, pipeline_version, engine_pair, bias_hash, passed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (config_hash, wer, boundary_error_rate, cer_thai, wer_latin,
         kind, pipeline_version, engine_pair, bias_hash, int(passed)),
    )
    conn.commit()
    return cur.lastrowid


def get_last_passing_eval(conn: sqlite3.Connection, kind: str = "transcribe") -> Optional[EvalRunRow]:
    # Filter by kind so a future CutDeck cut-quality run can never become the
    # transcription gate's baseline (or vice versa). id tie-breaks runs that
    # land within the same datetime('now') second.
    row = conn.execute(
        "SELECT * FROM eval_run WHERE passed = 1 AND kind = ? "
        "ORDER BY ran_at DESC, id DESC LIMIT 1",
        (kind,),
    ).fetchone()
    if row is None:
        return None
    r = dict(row)
    r["passed"] = bool(r["passed"])
    return EvalRunRow(**r)


def list_eval_runs(conn: sqlite3.Connection) -> list[EvalRunRow]:
    rows = conn.execute("SELECT * FROM eval_run ORDER BY ran_at DESC").fetchall()
    result = []
    for row in rows:
        r = dict(row)
        r["passed"] = bool(r["passed"])
        result.append(EvalRunRow(**r))
    return result
