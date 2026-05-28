CREATE TABLE IF NOT EXISTS media (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT    NOT NULL,
    duration_ms INTEGER,
    sha256      TEXT    NOT NULL UNIQUE,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS job (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id         INTEGER NOT NULL REFERENCES media(id),
    engine_a         TEXT    NOT NULL,
    engine_b         TEXT    NOT NULL,
    pipeline_version TEXT    NOT NULL,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    status           TEXT    NOT NULL DEFAULT 'pending'
    -- status: pending | running | done | failed
);

CREATE TABLE IF NOT EXISTS token (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        INTEGER NOT NULL REFERENCES job(id),
    idx           INTEGER NOT NULL,
    text          TEXT    NOT NULL,
    start_ms      INTEGER NOT NULL,
    end_ms        INTEGER NOT NULL,
    script        TEXT    NOT NULL CHECK (script IN ('thai', 'latin', 'other', 'mixed')),
    confidence    REAL,
    source_engine TEXT    NOT NULL CHECK (source_engine IN ('a', 'b', 'both', 'reconciler')),
    speaker_id    TEXT,   -- nullable, reserved for v2 diarization
    UNIQUE (job_id, idx)
);

CREATE TABLE IF NOT EXISTS correction (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id         INTEGER NOT NULL REFERENCES job(id),
    token_idx      INTEGER NOT NULL,
    raw_text       TEXT    NOT NULL,
    corrected_text TEXT    NOT NULL,
    error_type     TEXT,
    source_engine  TEXT    NOT NULL,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bias_term (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    term      TEXT NOT NULL,
    term_type TEXT NOT NULL CHECK (term_type IN ('brand', 'asset', 'technical', 'person', 'loanword')),
    script    TEXT,
    added_by  TEXT NOT NULL CHECK (added_by IN ('manual', 'flywheel')),
    weight    REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (term)
);

CREATE TABLE IF NOT EXISTS eval_run (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    config_hash         TEXT    NOT NULL,
    wer                 REAL    NOT NULL,
    boundary_error_rate REAL    NOT NULL,
    ran_at              TEXT    NOT NULL DEFAULT (datetime('now')),
    passed              INTEGER NOT NULL CHECK (passed IN (0, 1))
);
