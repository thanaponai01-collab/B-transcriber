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
    conn.executescript(_SCHEMA.read_text())
    _migrate(conn)
    conn.commit()
    conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Idempotent column additions for tables created before a schema bump.

    CREATE TABLE IF NOT EXISTS never alters an existing table, so new columns
    on eval_run must be added explicitly for pre-existing databases."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(eval_run)").fetchall()}
    if "cer_thai" not in cols:
        conn.execute("ALTER TABLE eval_run ADD COLUMN cer_thai REAL NOT NULL DEFAULT 1.0")
    if "wer_latin" not in cols:
        conn.execute("ALTER TABLE eval_run ADD COLUMN wer_latin REAL NOT NULL DEFAULT 1.0")


# ── dataclasses mirroring schema rows ─────────────────────────────────────────

@dataclass
class MediaRow:
    id: int
    path: str
    duration_ms: Optional[int]
    sha256: str
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


# ── correction ────────────────────────────────────────────────────────────────

def create_correction(
    conn: sqlite3.Connection,
    job_id: int,
    token_idx: int,
    raw_text: str,
    corrected_text: str,
    source_engine: str,
    error_type: Optional[str] = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO correction (job_id, token_idx, raw_text, corrected_text, error_type, source_engine)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (job_id, token_idx, raw_text, corrected_text, error_type, source_engine),
    )
    conn.commit()
    return cur.lastrowid


def get_corrections(conn: sqlite3.Connection, job_id: int) -> list[CorrectionRow]:
    rows = conn.execute(
        "SELECT * FROM correction WHERE job_id = ? ORDER BY token_idx", (job_id,)
    ).fetchall()
    return [CorrectionRow(**dict(r)) for r in rows]


def get_all_corrections(conn: sqlite3.Connection) -> list[CorrectionRow]:
    rows = conn.execute("SELECT * FROM correction ORDER BY created_at").fetchall()
    return [CorrectionRow(**dict(r)) for r in rows]


def get_correction_counts(conn: sqlite3.Connection) -> list[tuple[str, str, int]]:
    """Return (corrected_text, source_engine, count) aggregated in SQLite."""
    rows = conn.execute(
        "SELECT corrected_text, source_engine, COUNT(*) AS n "
        "FROM correction GROUP BY corrected_text, source_engine"
    ).fetchall()
    return [(r["corrected_text"], r["source_engine"], r["n"]) for r in rows]


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
) -> int:
    cur = conn.execute(
        "INSERT INTO eval_run (config_hash, wer, boundary_error_rate, cer_thai, wer_latin, passed) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (config_hash, wer, boundary_error_rate, cer_thai, wer_latin, int(passed)),
    )
    conn.commit()
    return cur.lastrowid


def get_last_passing_eval(conn: sqlite3.Connection) -> Optional[EvalRunRow]:
    row = conn.execute(
        "SELECT * FROM eval_run WHERE passed = 1 ORDER BY ran_at DESC LIMIT 1"
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
