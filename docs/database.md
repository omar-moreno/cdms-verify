# Database Schema

`cdms-verify` uses a single SQLite table. Run-level summary counts are **not**
stored — they are derived on demand, so they can never drift from the
underlying rows.

## `verification_results`

```sql
--8<-- "cdms_verify/schema.sql"
```

### Columns

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key. |
| `file_path` | TEXT | Absolute local path. **Unique** — enforces record-once. |
| `catalog_path` | TEXT | Derived CDMS catalog path (indexed for prefix queries). |
| `status` | TEXT | `VERIFIED`, `UNREGISTERED`, or `ERROR`. |
| `checksum` | TEXT | SHA256 hex digest, or `ERROR_CALCULATING`. |
| `size` | INTEGER | File size in bytes at scan time. |
| `mtime` | REAL | POSIX modification time (epoch seconds). |
| `site` | TEXT | Site storing the files being scanned. |
| `scan_timestamp` | TEXT | When the row was recorded. |

### Row lifecycle

Each file has exactly **one** row, keyed by the unique `file_path`:

- **First scan** inserts the row.
- **Re-checks** (of non-`VERIFIED` files) update the same row via an
  [upsert](api/database.md#cdms_verify.database.upsert_result)
  (`INSERT ... ON CONFLICT(file_path) DO UPDATE`). A file transitions from
  `UNREGISTERED` to `VERIFIED` in place — no duplicate rows are created.
- **`scan_timestamp`** therefore reflects the *most recent* time the file was
  checked, not just when it was first seen.

### Design rationale

- **No `verification_runs` table.** Summary counts (`total`, `registered`,
  `unregistered`, `errors`) are pure aggregates, computed via
  [`get_summary`](api/database.md#cdms_verify.database.get_summary).
- **No `local_dir` column.** It is derivable from `file_path` and nothing
  queries by it.
- **`size` and `mtime` are stored** so an external tool can perform its own
  change detection independently of this tool.


!!! info "Change detection is external"
    This tool records `size` and `mtime` but does not act on changes. Detecting
    modified files is the job of the data crawler.
