# cdms-verify

Verify local files against the CDMS Data Catalog and record results
to SQLite + CSV/HTML reports.

## Install

```bash
pip install -e ".[dev]"     # editable + dev deps
```

## Usage

```bash
cdms-verify --local-dir /path/to/CDMS/Raw --site SLAC --db-path results.db
```
