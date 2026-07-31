-- Schema for the CDMS verification results database.
-- Applied idempotently by cdms_verify.database.init_db().

CREATE TABLE IF NOT EXISTS verification_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_timestamp TEXT    NOT NULL,
    local_dir     TEXT    NOT NULL,
    catalog_path  TEXT    NOT NULL,
    site          TEXT    NOT NULL,
    total         INTEGER NOT NULL,
    registered    INTEGER NOT NULL,
    unregistered  INTEGER NOT NULL,
    errors        INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS verification_results (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER NOT NULL,
    file_path    TEXT    NOT NULL,
    catalog_path TEXT    NOT NULL,
    status       TEXT    NOT NULL,
    checksum     TEXT,
    FOREIGN KEY (run_id) REFERENCES verification_runs (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_results_run    ON verification_results (run_id);
CREATE INDEX IF NOT EXISTS idx_results_status ON verification_results (status);
