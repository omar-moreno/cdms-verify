# CDMS Verify

`cdms-verify` reconciles a local file tree against the **CDMS Data Catalog**.
It scans files, derives their expected catalog paths, checks registration
status, computes SHA256 checksums, and persists results to a SQLite database.

## How it works

1. **Scan** a local directory for files.
2. **Skip** any file already recorded in the database.
3. For each *new* file: derive its catalog path, stat it (size + mtime),
   compute its SHA256, and check whether it is registered at the target site.
4. **Persist** each result immediately (committed per file) so an interruption
   never loses completed work.

Reporting is intentionally **decoupled**: the CLI only *writes* to the
database. A separate read-only tool queries it (see
[Deployment](deployment.md)).

## Features

- **Record-once semantics** — a `UNIQUE(file_path)` constraint guarantees each
  file is stored exactly once; re-runs skip known files.
- **Incremental durability** — results are committed per file.
- **Zero-config storage** — a single SQLite `.db` file, ideal for k8s CronJobs.
- **Derived summaries** — status counts are computed on demand, never stored,
  so they cannot drift.
