from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_SCHEMA = Path(__file__).parent / "schema.sql"
_DEFAULT_DB = Path(__file__).parent.parent.parent / "transcriber.db"

_REPO_ROOT = _DEFAULT_DB.parent


def resolve_db_path(config: Optional[dict] = None) -> Path:
    """The one database every tool shares: `store.path` from config.yaml, resolved
    against the repo root when relative (never the CWD), else the default
    `transcriber.db`."""
    configured = ((config or {}).get("store") or {}).get("path")
    if not configured:
        return _DEFAULT_DB
    path = Path(configured)
    return path if path.is_absolute() else _REPO_ROOT / path


_NOT_A_COLUMN = {"PRIMARY", "UNIQUE", "FOREIGN", "CHECK", "CONSTRAINT"}


def _schema_columns(table: str) -> list[tuple[str, str]]:
    text = _SCHEMA.read_text(encoding="utf-8")
    match = re.search(
        rf"CREATE TABLE IF NOT EXISTS {re.escape(table)}\s*\((.*?)\n\);",
        text,
        re.DOTALL,
    )
    if match is None:
        raise ValueError(f"no CREATE TABLE block for {table!r} in schema.sql")

    body = "\n".join(line.split("--", 1)[0] for line in match.group(1).splitlines())

    fragments: list[str] = []
    depth = 0
    current = ""
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            fragments.append(current)
            current = ""
        else:
            current += ch
    fragments.append(current)

    columns = []
    for frag in fragments:
        frag = " ".join(frag.split())
        if not frag:
            continue
        name = frag.split(" ", 1)[0]
        if name.upper() in _NOT_A_COLUMN or "PRIMARY KEY" in frag.upper():
            continue
        columns.append((name, frag))
    return columns


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
    """CREATE TABLE IF NOT EXISTS never alters an existing table, so new columns
    must be added explicitly for pre-existing databases."""
    def _add(table: str, column: str, ddl: str) -> None:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

    tables = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", _SCHEMA.read_text(encoding="utf-8"))
    for table in tables:
        for name, ddl in _schema_columns(table):
            _add(table, name, ddl)


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
    resume_fingerprint: Optional[str] = None
    chosen_at: Optional[str] = None


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
    raw_segments_json: Optional[str] = None


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
    is_experiment: bool = False
    metrics_version: int = 1
    cue_boundary_error_rate: float = 0.0
    overlapping_cues: int = 0
    cue_count_delta: Optional[int] = None
    shortest_cue_ms: Optional[float] = None
    nonzero_gap_count: Optional[int] = None
    cer_thai_ci_lo: Optional[float] = None
    cer_thai_ci_hi: Optional[float] = None
    wer_latin_ci_lo: Optional[float] = None
    wer_latin_ci_hi: Optional[float] = None
    boundary_error_rate_ci_lo: Optional[float] = None
    boundary_error_rate_ci_hi: Optional[float] = None
    cue_boundary_error_rate_ci_lo: Optional[float] = None
    cue_boundary_error_rate_ci_hi: Optional[float] = None
    rtf: Optional[float] = None
    gate_unresolved: Optional[str] = None
    cue_legality_violations: Optional[int] = None
    speech_coverage_miss: float = 0.0
    orphan_cues: Optional[int] = None
    speech_coverage_miss_ci_lo: Optional[float] = None
    speech_coverage_miss_ci_hi: Optional[float] = None
    cer_thai_sub: Optional[float] = None
    cer_thai_del: Optional[float] = None
    cer_thai_ins: Optional[float] = None
    cer_thai_spread: Optional[float] = None
    cer_thai_spread_ci_lo: Optional[float] = None
    cer_thai_spread_ci_hi: Optional[float] = None
    baseline_eval_id: Optional[int] = None
    paired_delta_ci_json: Optional[str] = None
    gate_status: Optional[str] = None


@dataclass
class EvalRun:
    """What a caller writes: `EvalRunRow` minus the database-assigned fields.

    `metrics_version=None` means "stamp the current metric definitions' version".
    """

    config_hash: str
    wer: float
    boundary_error_rate: float
    passed: bool
    cer_thai: float = 1.0
    wer_latin: float = 1.0
    kind: str = "transcribe"
    pipeline_version: Optional[str] = None
    engine_pair: Optional[str] = None
    bias_hash: Optional[str] = None
    is_experiment: bool = False
    metrics_version: Optional[int] = None
    cue_boundary_error_rate: float = 0.0
    overlapping_cues: int = 0
    cue_count_delta: Optional[int] = None
    shortest_cue_ms: Optional[float] = None
    nonzero_gap_count: Optional[int] = None
    cer_thai_ci_lo: Optional[float] = None
    cer_thai_ci_hi: Optional[float] = None
    wer_latin_ci_lo: Optional[float] = None
    wer_latin_ci_hi: Optional[float] = None
    boundary_error_rate_ci_lo: Optional[float] = None
    boundary_error_rate_ci_hi: Optional[float] = None
    cue_boundary_error_rate_ci_lo: Optional[float] = None
    cue_boundary_error_rate_ci_hi: Optional[float] = None
    rtf: Optional[float] = None
    gate_unresolved: Optional[str] = None
    cue_legality_violations: Optional[int] = None
    speech_coverage_miss: float = 0.0
    orphan_cues: Optional[int] = None
    speech_coverage_miss_ci_lo: Optional[float] = None
    speech_coverage_miss_ci_hi: Optional[float] = None
    cer_thai_sub: Optional[float] = None
    cer_thai_del: Optional[float] = None
    cer_thai_ins: Optional[float] = None
    cer_thai_spread: Optional[float] = None
    cer_thai_spread_ci_lo: Optional[float] = None
    cer_thai_spread_ci_hi: Optional[float] = None
    baseline_eval_id: Optional[int] = None
    paired_delta_ci_json: Optional[str] = None
    gate_status: Optional[str] = None


def sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def create_media(
    conn: sqlite3.Connection,
    path: str,
    duration_ms: Optional[int] = None,
    sha256: Optional[str] = None,
) -> int:
    digest = sha256 if sha256 is not None else sha256_of_file(path)
    cur = conn.execute(
        "INSERT OR IGNORE INTO media (path, duration_ms, sha256) VALUES (?, ?, ?)",
        (path, duration_ms, digest),
    )
    if duration_ms is not None and not cur.lastrowid:
        conn.execute(
            "UPDATE media SET duration_ms = ? WHERE sha256 = ? AND duration_ms IS NULL",
            (duration_ms, digest),
        )
    conn.commit()
    if cur.lastrowid:
        return cur.lastrowid
    row = conn.execute("SELECT id FROM media WHERE sha256 = ?", (digest,)).fetchone()
    return row["id"]


def set_media_duration(conn: sqlite3.Connection, media_id: int, duration_ms: int) -> None:
    conn.execute("UPDATE media SET duration_ms = ? WHERE id = ?", (duration_ms, media_id))
    conn.commit()


def get_media_by_sha256(conn: sqlite3.Connection, sha256: str) -> Optional[MediaRow]:
    row = conn.execute("SELECT * FROM media WHERE sha256 = ?", (sha256,)).fetchone()
    if row is None:
        return None
    return MediaRow(**dict(row))


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
    conn.execute(
        "UPDATE media SET fps_num = ?, fps_den = ?, is_vfr = ? WHERE id = ?",
        (fps_num, fps_den, int(is_vfr), media_id),
    )
    conn.commit()


def create_job(
    conn: sqlite3.Connection,
    media_id: int,
    engine_a: str,
    engine_b: str,
    pipeline_version: str,
    resume_fingerprint: Optional[str] = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO job (media_id, engine_a, engine_b, pipeline_version, resume_fingerprint) "
        "VALUES (?, ?, ?, ?, ?)",
        (media_id, engine_a, engine_b, pipeline_version, resume_fingerprint),
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
    resume_fingerprint: Optional[str] = None,
) -> Optional[JobRow]:
    """The most recent 'failed' or 'running' job for this exact (media, engine pair,
    pipeline version, resume fingerprint). Legacy callers without a fingerprint
    only match legacy jobs. Fingerprinted runs never reuse unknown settings.
    """
    row = conn.execute(
        "SELECT * FROM job WHERE media_id = ? AND engine_a = ? AND engine_b = ? "
        "AND pipeline_version = ? AND resume_fingerprint IS ? "
        "AND status IN ('failed', 'running') ORDER BY id DESC LIMIT 1",
        (media_id, engine_a, engine_b, pipeline_version, resume_fingerprint),
    ).fetchone()
    if row is None:
        return None
    return JobRow(**dict(row))


def find_finished_job(
    conn: sqlite3.Connection,
    media_id: int,
    engine_a: str,
    engine_b: str,
    pipeline_version: str,
    resume_fingerprint: Optional[str] = None,
) -> Optional[JobRow]:
    """The most recent completed job for this exact (media, engine pair, pipeline
    version, resume fingerprint) that still holds its tokens."""
    row = conn.execute(
        "SELECT * FROM job WHERE media_id = ? AND engine_a = ? AND engine_b = ? "
        "AND pipeline_version = ? AND resume_fingerprint IS ? "
        "AND status = 'done' AND job_phase = 'written' "
        "AND EXISTS (SELECT 1 FROM token WHERE token.job_id = job.id) "
        "ORDER BY id DESC LIMIT 1",
        (media_id, engine_a, engine_b, pipeline_version, resume_fingerprint),
    ).fetchone()
    if row is None:
        return None
    return JobRow(**dict(row))


_FINISHED_TRANSCRIPTS = (
    "FROM job JOIN media ON media.id = job.media_id WHERE media.sha256 = ? "
    "AND job.status = 'done' AND job.job_phase = 'written' "
    "AND EXISTS (SELECT 1 FROM token WHERE token.job_id = job.id) ")


def latest_transcript_job(conn: sqlite3.Connection, sha256: str) -> Optional[JobRow]:
    """The most recently chosen finished job (`mark_transcript_chosen`, else the newest), of any
    engine or fingerprint, that still holds tokens for the media with this sha256."""
    row = conn.execute(
        "SELECT job.* " + _FINISHED_TRANSCRIPTS
        + "ORDER BY COALESCE(job.chosen_at, job.created_at) DESC, job.id DESC LIMIT 1",
        (sha256,),
    ).fetchone()
    return JobRow(**dict(row)) if row else None


def mark_transcript_chosen(conn: sqlite3.Connection, job_id: int) -> None:
    """Make this job the file's transcript for `latest_transcript_job`."""
    conn.execute("UPDATE job SET chosen_at = strftime('%Y-%m-%d %H:%M:%f', 'now') WHERE id = ?", (job_id,))
    conn.commit()


def transcript_scripts(conn: sqlite3.Connection, sha256: str) -> dict[int, str]:
    """{job id: "thai" or "latin"} for every finished transcript of this file: the script most of
    its tokens are in ("mixed" counts as Thai). "other" is ignored,
    so a job with only "other" tokens (music, numbers) has no language and is left out."""
    rows = conn.execute(
        "SELECT job.id AS id, "
        "SUM(t.script IN ('thai', 'mixed')) AS thai, SUM(t.script = 'latin') AS latin "
        + _FINISHED_TRANSCRIPTS.replace("FROM job", "FROM job JOIN token t ON t.job_id = job.id", 1)
        + "GROUP BY job.id ORDER BY job.id",
        (sha256,),
    ).fetchall()
    return {r["id"]: "thai" if r["thai"] >= r["latin"] else "latin" for r in rows if r["thai"] or r["latin"]}


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
    conn.execute("DELETE FROM token WHERE job_id = ?", (job_id,))
    conn.commit()


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
    conn.execute(
        "DELETE FROM correction WHERE job_id = ? AND token_idx = ?",
        (job_id, token_idx),
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
    """Return (term, source_engine, count).

    `term` is the minimal promotable span; rows without
    a span fall back to the full corrected cue."""
    rows = conn.execute(
        "SELECT COALESCE(corrected_span, corrected_text) AS term, source_engine, COUNT(*) AS n "
        "FROM correction GROUP BY term, source_engine"
    ).fetchall()
    return [(r["term"], r["source_engine"], r["n"]) for r in rows]


def bulk_create_speech_spans(conn: sqlite3.Connection, job_id: int, spans: list[dict]) -> None:
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
    conn.execute("DELETE FROM speech_span WHERE job_id = ?", (job_id,))
    conn.commit()


def purge_job_transcript_data(conn: sqlite3.Connection, job_id: int) -> None:
    """Drop a job's per-run bulk rows (tokens, speech spans, engine results) but
    keep the media/job rows, so cut_plan rows referencing the job stay valid."""
    for table in ("token", "speech_span", "engine_result"):
        conn.execute(f"DELETE FROM {table} WHERE job_id = ?", (job_id,))
    conn.commit()


def save_engine_segments(conn: sqlite3.Connection, job_id: int, engine_slot: str,
                         raw_segments_json: str) -> None:
    conn.execute("UPDATE engine_result SET raw_segments_json = ? WHERE job_id = ? AND engine_slot = ?",
                 (raw_segments_json, job_id, engine_slot))
    conn.commit()


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
    return {r.term: r.weight for r in get_bias_terms(conn)}


def delete_bias_term(conn: sqlite3.Connection, term: str) -> None:
    conn.execute("DELETE FROM bias_term WHERE term = ?", (term,))
    conn.commit()


_EVAL_RUN_COLUMNS = (
    "config_hash", "wer", "boundary_error_rate", "cer_thai", "wer_latin",
    "kind", "pipeline_version", "engine_pair", "bias_hash", "is_experiment",
    "metrics_version", "cue_boundary_error_rate", "overlapping_cues",
    "cue_count_delta", "shortest_cue_ms", "nonzero_gap_count",
    "cer_thai_ci_lo", "cer_thai_ci_hi", "wer_latin_ci_lo", "wer_latin_ci_hi",
    "boundary_error_rate_ci_lo", "boundary_error_rate_ci_hi",
    "cue_boundary_error_rate_ci_lo", "cue_boundary_error_rate_ci_hi",
    "rtf", "gate_unresolved", "cue_legality_violations", "baseline_eval_id",
    "paired_delta_ci_json", "gate_status",
    "speech_coverage_miss", "orphan_cues",
    "speech_coverage_miss_ci_lo", "speech_coverage_miss_ci_hi",
    "cer_thai_sub", "cer_thai_del", "cer_thai_ins",
    "cer_thai_spread", "cer_thai_spread_ci_lo", "cer_thai_spread_ci_hi", "passed",
)

_EVAL_RUN_COERCE = {
    "is_experiment": int, "passed": int, "metrics_version": int,
    "cue_boundary_error_rate": float, "overlapping_cues": int,
    "speech_coverage_miss": float,
}


def create_eval_run(conn: sqlite3.Connection, run: EvalRun,
                    clip_metrics: Optional[dict[str, str]] = None) -> int:
    metrics_version = run.metrics_version
    if metrics_version is None:
        from transcribe.eval.metrics import METRICS_VERSION
        metrics_version = METRICS_VERSION

    values = []
    for column in _EVAL_RUN_COLUMNS:
        value = metrics_version if column == "metrics_version" else getattr(run, column)
        coerce = _EVAL_RUN_COERCE.get(column)
        values.append(coerce(value) if coerce is not None else value)

    with conn:
        cur = conn.execute(
            f"INSERT INTO eval_run ({', '.join(_EVAL_RUN_COLUMNS)}) "
            f"VALUES ({', '.join('?' * len(_EVAL_RUN_COLUMNS))})",
            tuple(values),
        )
        eval_id = cur.lastrowid
        if clip_metrics:
            conn.executemany(
                "INSERT INTO eval_clip (eval_run_id, clip_key, metrics_json) VALUES (?, ?, ?)",
                [(eval_id, key, blob) for key, blob in clip_metrics.items()],
            )
    return eval_id


def get_eval_clip_metrics(conn: sqlite3.Connection, eval_run_id: int) -> dict[str, str]:
    rows = conn.execute(
        "SELECT clip_key, metrics_json FROM eval_clip WHERE eval_run_id = ? ORDER BY clip_key",
        (eval_run_id,),
    ).fetchall()
    return {row["clip_key"]: row["metrics_json"] for row in rows}


def _eval_row(row: sqlite3.Row) -> EvalRunRow:
    r = dict(row)
    r["passed"] = bool(r["passed"])
    r["is_experiment"] = bool(r.get("is_experiment", 0))
    return EvalRunRow(**r)


def get_last_passing_eval(
    conn: sqlite3.Connection,
    kind: str = "transcribe",
    metrics_version: Optional[int] = None,
) -> Optional[EvalRunRow]:
    if metrics_version is None:
        from transcribe.eval.metrics import METRICS_VERSION
        metrics_version = METRICS_VERSION
    row = conn.execute(
        "SELECT * FROM eval_run WHERE passed = 1 AND kind = ? AND is_experiment = 0 "
        "AND metrics_version = ? AND gate_unresolved IS NULL "
        "AND (gate_status IS NULL OR gate_status = 'pass') "
        "ORDER BY ran_at DESC, id DESC LIMIT 1",
        (kind, int(metrics_version)),
    ).fetchone()
    if row is None:
        return None
    return _eval_row(row)


def list_eval_runs(conn: sqlite3.Connection) -> list[EvalRunRow]:
    rows = conn.execute("SELECT * FROM eval_run ORDER BY ran_at DESC").fetchall()
    return [_eval_row(row) for row in rows]
