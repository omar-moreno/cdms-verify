-- Single-table schema for CDMS verification results.
-- Each file is recorded exactly once (enforced by UNIQUE(file_path)); the CLI
-- skips files already present. Run-level counts are derived on demand rather
-- than stored, so there is no separate runs table.

CREATE TABLE IF NOT EXISTS verification_results (
    id             INTEGER  PRIMARY KEY AUTOINCREMENT,
    file_path      TEXT     NOT NULL UNIQUE, -- absolute local path; recorded once
    catalog_path   TEXT     NOT NULL,        -- derived CDMS catalog path
    status         TEXT     NOT NULL,        -- VERIFIED | UNREGISTERED | ERROR
    checksum       TEXT,                     -- SHA256 hex, or error sentinel
    size           INTEGER,                  -- bytes at scan time
    mtime          REAL,                     -- POSIX mtime (epoch seconds)
    site           TEXT     NOT NULL,        -- catalog site queried when found
    scan_timestamp TEXT     NOT NULL         -- when this record was recorded
);

CREATE INDEX IF NOT EXISTS idx_results_status    ON verification_results (status);
CREATE INDEX IF NOT EXISTS idx_results_catalog   ON verification_results (catalog_path);
