# Usage

## Command-line

```bash
cdms-verify \
  --local-dir /sdf/data/supercdms/data/CDMS/SNOLAB \
  --site SLAC \
  --db-path verification.db
```

### Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--local-dir` | `-d` | *(required)* | Directory to verify. |
| `--site` | `-s` | `SLAC` | Site where the files are located |
| `--recursive/--no-recursive` | `-r/-nr` | `True` | Recurse into subdirs. |
| `--db-path` | | `verification.db` | SQLite results database. |
| `--verbose` | `-v` | `False` | Verbose per-file output. |

### Skip-and-persist behavior

- Files already recorded in the database (matched by `file_path`) are
  **skipped** — not re-checksummed, not re-checked, not re-inserted.
- Only **new** files are processed.
- Each new file is **committed immediately**, so interrupting the run keeps
  all files completed up to that point.

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | All new files verified (or no new files found). |
| `1` | Discrepancies found among new files (unregistered or errors). |
| `2` | Usage/validation error (e.g. missing `--local-dir`). |

These map cleanly to Kubernetes Job success/failure semantics.

## Querying results

The database is the source of truth. Inspect it with plain SQL:

```sql
-- All files under a catalog path prefix
SELECT file_path, status, checksum, scan_timestamp
FROM verification_results
WHERE catalog_path = '/CDMS/Raw'
   OR catalog_path LIKE '/CDMS/Raw/%'
ORDER BY catalog_path;

-- Everything still unregistered
SELECT file_path, catalog_path
FROM verification_results
WHERE status = 'UNREGISTERED';
```
