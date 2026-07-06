CREATE TABLE IF NOT EXISTS media (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT    NOT NULL,
    duration_ms INTEGER,
    sha256      TEXT    NOT NULL UNIQUE,
    -- Timebase (GAP-1): the source media's true rational frame rate. NULL until
    -- probed. fps stored as an integer pair only — never a decimal fps.
    fps_num     INTEGER,
    fps_den     INTEGER,
    is_vfr      INTEGER NOT NULL DEFAULT 0,  -- GAP-2: variable-frame-rate flag
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
    corrected_text TEXT    NOT NULL,   -- full corrected cue (audit + editor display)
    -- 5.3: minimal changed word/phrase extracted from the cue diff. This — not the
    -- whole ~7s cue — is the unit the flywheel promotes to a bias term. NULL on
    -- pre-5.3 rows; promotion falls back to corrected_text for those.
    corrected_span TEXT,
    error_type     TEXT,
    source_engine  TEXT    NOT NULL,
    -- GAP-7: coarse reason tag (misheard | spelling | code-switch boundary |
    -- name-term | style | other). Optional — never blocks a save. Feeds the
    -- level-2 taste rubric later.
    reason         TEXT,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- VAD master timeline (GAP-3). Silero speech/silence spans persisted so CutDeck
-- and the hallucination filter can use them. One row per span, ordered by idx.
CREATE TABLE IF NOT EXISTS speech_span (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id    INTEGER NOT NULL REFERENCES job(id),
    idx       INTEGER NOT NULL,
    start_ms  INTEGER NOT NULL,
    end_ms    INTEGER NOT NULL,
    kind      TEXT    NOT NULL CHECK (kind IN ('speech', 'silence')),
    UNIQUE (job_id, idx)
);

-- CutDeck Layer-4 artifact (Part B). The proposed/edited rough cut for a job,
-- stored as versioned CutPlan JSON. One row per proposal; status tracks the
-- round-trip lifecycle. plan_json is the single source of truth for the spans —
-- the columns are denormalized handles for listing and the flywheel.
CREATE TABLE IF NOT EXISTS cut_plan (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id       INTEGER NOT NULL REFERENCES job(id),
    plan_version TEXT    NOT NULL,
    plan_json    TEXT    NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'proposed'
                 CHECK (status IN ('proposed', 'reviewed', 'exported', 'reimported')),
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
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
    wer                 REAL    NOT NULL,  -- overall word-level WER (coarse signal)
    boundary_error_rate REAL    NOT NULL,  -- temporal switch-point error (1 - F1)
    cer_thai            REAL    NOT NULL DEFAULT 1.0,  -- primary Thai signal (char error rate)
    wer_latin           REAL    NOT NULL DEFAULT 1.0,  -- primary Latin signal (word error rate)
    -- Attribution (A.2): make a regression traceable to the pipeline build,
    -- the active engine pair, and the bias index that produced it. 'kind'
    -- separates transcriber runs from CutDeck cut-quality runs (Part B eval).
    kind                TEXT    NOT NULL DEFAULT 'transcribe',
    pipeline_version    TEXT,
    engine_pair         TEXT,
    bias_hash           TEXT,
    ran_at              TEXT    NOT NULL DEFAULT (datetime('now')),
    passed              INTEGER NOT NULL CHECK (passed IN (0, 1))
);
