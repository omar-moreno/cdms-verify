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

### Re-check behavior

On each run, `cdms-verify` decides per file whether to process it based on its
recorded status:

| Recorded status | Action | Why |
|-----------------|--------|-----|
| `VERIFIED` | **Skipped** | Terminal success — the file is confirmed in the catalog. |
| `UNREGISTERED` | **Re-checked** | It may have been registered since the last run. |
| `ERROR` | **Re-checked** | A prior checksum failure may now succeed. |
| *(not in database)* | **Processed** | A newly-discovered file. |

Re-checked files **update their existing row** in place (an upsert keyed on
`file_path`), so a file transitions from `UNREGISTERED` → `VERIFIED` without
creating a duplicate. Each write is committed immediately for crash durability.

!!! note "Verified files are never re-checked"
    Once a file is `VERIFIED` it is skipped on all subsequent runs, even if it
    later disappears from the catalog. `VERIFIED` is treated as a terminal
    state.

## Exit codes

| Code | Meaning |
|:----:|---------|
| `0` | ✅ All processed files verified (or nothing to do). |
| `1` | ⚠️ Discrepancies found (unregistered files or errors). |
| `2` | ❌ Usage/validation error (e.g. missing `--local-dir`). |

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

Or browse results interactively with the
[PHP report page](web-report.md).
