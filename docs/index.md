# CDMS Verify

`cdms-verify` reconciles a local file tree against the **CDMS Data Catalog**.
It scans files, derives their expected catalog paths, checks registration
status, computes SHA256 checksums, and persists results to a SQLite database.

## How it works

1. **Scan** a local directory for files.
2. **Skip** files already recorded as `VERIFIED` (a terminal state).
3. For every other file — new, `UNREGISTERED`, or `ERROR` — derive its catalog
   path, stat it (size + mtime), compute its SHA256, and check whether it is
   registered at the target site.
4. **Upsert** each result immediately (committed per file) so an interruption
   never loses completed work, and re-checked files update in place.

Reporting is intentionally **decoupled**: the CLI only *writes* to the
database. A separate read-only tool queries it (see
[Deployment](deployment.md) and the [PHP report page](web-report.md))

## Features

- **Re-check semantics** — `VERIFIED` files are skipped; `UNREGISTERED` and
  `ERROR` files are re-checked each run and updated in place.
- **Record-once identity** — a `UNIQUE(file_path)` constraint means each file
  has exactly one row; re-checks update it via upsert.
- **Incremental durability** — every result is committed per file.
- **Zero-config storage** — a single SQLite `.db` file, ideal for k8s CronJobs.
- **Drift-free summaries** — status counts are computed on demand, never stored.
- **Change-detection ready** — stores `size` and `mtime` for external tools.

## Quick start

```bash
pip install cdms-verify
cdms-verify --local-dir /sdf/data/supercdms/data/CDMS/SNOLAB/ --site SLAC --db-path verification.db
```

See [Usage](usage.md) for all options and the [API Reference](api/paths.md)
for module documentation.
