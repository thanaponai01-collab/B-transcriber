"""eval_run's schema used to exist in two hand-typed places: the CREATE TABLE
in schema.sql and a parallel list of `_add(...)` calls in `_migrate`, with
nothing keeping a column's name/type/nullability/default in agreement between
them (issue #15). `_migrate` now parses its eval_run column list out of
schema.sql instead of re-declaring it, so the two paths cannot diverge. These
tests are the guard against that regressing.

Run: python -m pytest tests/test_eval_run_schema_migration.py -v
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe.db import store


def _tmp_path():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return Path(f.name)


def _table_info(conn, table):
    """(name, type, notnull, dflt_value) in column order. pk is excluded —
    ALTER TABLE ADD COLUMN can never add or change one, so it is out of scope
    for a migration-generated column."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [(r["name"], r["type"], r["notnull"], r["dflt_value"]) for r in rows]


# A pre-Phase-A eval_run: the shape before bootstrap CIs/RTF/gate_unresolved/
# cue_legality_violations existed, lifted from an earlier schema.sql rather
# than paraphrased, so the migration test exercises a real old column set —
# the path an existing developer's transcriber.db actually takes.
_PRE_PHASE_A_EVAL_RUN = """
CREATE TABLE eval_run (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    config_hash         TEXT    NOT NULL,
    wer                 REAL    NOT NULL,
    boundary_error_rate REAL    NOT NULL,
    cer_thai            REAL    NOT NULL DEFAULT 1.0,
    wer_latin           REAL    NOT NULL DEFAULT 1.0,
    kind                TEXT    NOT NULL DEFAULT 'transcribe',
    pipeline_version    TEXT,
    engine_pair         TEXT,
    bias_hash           TEXT,
    is_experiment       INTEGER NOT NULL DEFAULT 0,
    metrics_version     INTEGER NOT NULL DEFAULT 1,
    cue_boundary_error_rate REAL    NOT NULL DEFAULT 0.0,
    overlapping_cues        INTEGER NOT NULL DEFAULT 0,
    cue_count_delta         INTEGER,
    shortest_cue_ms         REAL,
    nonzero_gap_count       INTEGER,
    ran_at              TEXT    NOT NULL DEFAULT (datetime('now')),
    passed              INTEGER NOT NULL
);
"""

_PHASE_A_COLUMNS = {
    "cer_thai_ci_lo", "cer_thai_ci_hi",
    "wer_latin_ci_lo", "wer_latin_ci_hi",
    "boundary_error_rate_ci_lo", "boundary_error_rate_ci_hi",
    "cue_boundary_error_rate_ci_lo", "cue_boundary_error_rate_ci_hi",
    "rtf", "gate_unresolved", "cue_legality_violations",
}


def test_schema_created_and_migrated_databases_agree():
    """The headline test: a freshly created database (CREATE TABLE path) and
    an old database walked forward by _migrate (ALTER TABLE path) must end up
    with the same eval_run columns — same names, types, nullability and
    defaults. Column *order* legitimately differs (ALTER TABLE always appends
    at the end, regardless of a column's position in schema.sql, and store.py
    only ever accesses columns by name), so this compares as sets."""
    fresh_db = _tmp_path()
    store.init_db(fresh_db)
    fresh_conn = store.connect(fresh_db)

    migrated_db = _tmp_path()
    migrated_conn = store.connect(migrated_db)
    migrated_conn.executescript(_PRE_PHASE_A_EVAL_RUN)
    # Mirror init_db's real sequence: the schema script creates every other
    # table (IF NOT EXISTS — eval_run already exists so it's left alone), then
    # _migrate backfills columns on top of the old eval_run shape.
    migrated_conn.executescript(store._SCHEMA.read_text(encoding="utf-8"))
    store._migrate(migrated_conn)
    migrated_conn.commit()

    try:
        assert set(_table_info(fresh_conn, "eval_run")) == set(_table_info(migrated_conn, "eval_run"))
    finally:
        fresh_conn.close()
        migrated_conn.close()


def test_init_db_schema_is_unchanged():
    """Pins today's exact eval_run shape (name, type, notnull, default, and
    schema.sql's declared order) so this refactor — and any future one —
    cannot silently add, drop, retype, re-default or reorder a column."""
    db = _tmp_path()
    store.init_db(db)
    conn = store.connect(db)
    try:
        assert _table_info(conn, "eval_run") == [
            ("id", "INTEGER", 0, None),
            ("config_hash", "TEXT", 1, None),
            ("wer", "REAL", 1, None),
            ("boundary_error_rate", "REAL", 1, None),
            ("cer_thai", "REAL", 1, "1.0"),
            ("wer_latin", "REAL", 1, "1.0"),
            ("kind", "TEXT", 1, "'transcribe'"),
            ("pipeline_version", "TEXT", 0, None),
            ("engine_pair", "TEXT", 0, None),
            ("bias_hash", "TEXT", 0, None),
            ("is_experiment", "INTEGER", 1, "0"),
            ("metrics_version", "INTEGER", 1, "1"),
            ("cue_boundary_error_rate", "REAL", 1, "0.0"),
            ("overlapping_cues", "INTEGER", 1, "0"),
            ("cue_count_delta", "INTEGER", 0, None),
            ("shortest_cue_ms", "REAL", 0, None),
            ("nonzero_gap_count", "INTEGER", 0, None),
            ("cer_thai_ci_lo", "REAL", 0, None),
            ("cer_thai_ci_hi", "REAL", 0, None),
            ("wer_latin_ci_lo", "REAL", 0, None),
            ("wer_latin_ci_hi", "REAL", 0, None),
            ("boundary_error_rate_ci_lo", "REAL", 0, None),
            ("boundary_error_rate_ci_hi", "REAL", 0, None),
            ("cue_boundary_error_rate_ci_lo", "REAL", 0, None),
            ("cue_boundary_error_rate_ci_hi", "REAL", 0, None),
            ("rtf", "REAL", 0, None),
            ("gate_unresolved", "TEXT", 0, None),
            ("cue_legality_violations", "INTEGER", 0, None),
            ("ran_at", "TEXT", 1, "datetime('now')"),
            ("passed", "INTEGER", 1, None),
        ]
    finally:
        conn.close()


def test_migrate_adds_every_phase_a_column_with_correct_shape():
    """Exercises the path a developer's existing pre-Phase-A transcriber.db
    actually takes: _migrate must add every Phase A column, nullable, with no
    default (all eleven are genuinely optional — NULL means 'predates this
    column', per schema.sql's own comment)."""
    db = _tmp_path()
    conn = store.connect(db)
    conn.executescript(_PRE_PHASE_A_EVAL_RUN)
    conn.executescript(store._SCHEMA.read_text(encoding="utf-8"))
    before = {r[0] for r in _table_info(conn, "eval_run")}
    assert not (before & _PHASE_A_COLUMNS), "fixture already has a Phase A column"

    store._migrate(conn)
    conn.commit()

    after = {name: (notnull, default) for name, _typ, notnull, default in _table_info(conn, "eval_run")}
    assert _PHASE_A_COLUMNS <= after.keys()
    for name in _PHASE_A_COLUMNS:
        notnull, default = after[name]
        assert notnull == 0, f"{name} should be nullable"
        assert default is None, f"{name} should have no default"
    conn.close()


def test_migrate_is_idempotent():
    """Re-running init_db must not raise and must not change the schema —
    _add's PRAGMA table_info(...) existence check has to keep working now that
    the column list driving it comes from parsing schema.sql instead of a
    literal string."""
    db = _tmp_path()
    store.init_db(db)
    conn = store.connect(db)
    before = _table_info(conn, "eval_run")
    conn.close()

    store.init_db(db)  # second run: every column already exists
    conn = store.connect(db)
    after = _table_info(conn, "eval_run")
    conn.close()

    assert before == after


def test_eval_run_round_trip_preserves_every_field():
    """Every field EvalRun exposes — including the CI bounds, rtf,
    gate_unresolved and cue_legality_violations this migration list covers —
    must come back unchanged through create_eval_run/list_eval_runs."""
    db = _tmp_path()
    store.init_db(db)
    conn = store.connect(db)
    try:
        run = store.EvalRun(
            config_hash="c", wer=0.1, boundary_error_rate=0.2, passed=True,
            cer_thai=0.3, wer_latin=0.4, kind="transcribe",
            pipeline_version="v1", engine_pair="a+b", bias_hash="h",
            is_experiment=False, metrics_version=3,
            cue_boundary_error_rate=0.5, overlapping_cues=1,
            cue_count_delta=2, shortest_cue_ms=100.0, nonzero_gap_count=3,
            cer_thai_ci_lo=0.1, cer_thai_ci_hi=0.5,
            wer_latin_ci_lo=0.2, wer_latin_ci_hi=0.6,
            boundary_error_rate_ci_lo=0.3, boundary_error_rate_ci_hi=0.7,
            cue_boundary_error_rate_ci_lo=0.4, cue_boundary_error_rate_ci_hi=0.8,
            rtf=1.5, gate_unresolved="cer_thai", cue_legality_violations=4,
        )
        store.create_eval_run(conn, run)
        [back] = store.list_eval_runs(conn)
        for field in (
            "config_hash", "wer", "boundary_error_rate", "cer_thai",
            "wer_latin", "kind", "pipeline_version", "engine_pair",
            "bias_hash", "metrics_version", "cue_boundary_error_rate",
            "overlapping_cues", "cue_count_delta", "shortest_cue_ms",
            "nonzero_gap_count", "cer_thai_ci_lo", "cer_thai_ci_hi",
            "wer_latin_ci_lo", "wer_latin_ci_hi",
            "boundary_error_rate_ci_lo", "boundary_error_rate_ci_hi",
            "cue_boundary_error_rate_ci_lo", "cue_boundary_error_rate_ci_hi",
            "rtf", "gate_unresolved", "cue_legality_violations",
        ):
            assert getattr(back, field) == getattr(run, field), field
        assert back.is_experiment is False
    finally:
        conn.close()
