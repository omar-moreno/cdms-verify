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

!!! info "Change detection is external"
    This tool records `size` and `mtime` but does not act on changes. Detecting
    modified files is the job of the data crawler.
