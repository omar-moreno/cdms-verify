# Development

## Running tests

```bash
pip install -e ".[dev]"
pytest -v
# with coverage
pytest --cov=cdms_verify --cov-report=term-missing
```

## Building the docs

```bash
pip install -e ".[docs]"
mkdocs serve   # live preview at http://127.0.0.1:8000
mkdocs build   # static site into ./site
```

## Project layout

```
cdms_verify/
├── paths.py       # path normalization + catalog-path extraction
├── scanning.py    # filesystem scan, checksum, stat
├── catalog.py     # catalog query wrapper
├── database.py    # single-table SQLite persistence
├── schema.sql     # database schema
└── cli.py         # Click entry point (scan + skip + persist)
tests/
├── test_paths.py
├── test_scanning.py
├── test_database.py
└── test_cli.py
```

## Conventions

- **Docstrings:** NumPy style, rendered via `mkdocstrings`.
- **Type hints:** required on all public functions.
- **Error handling:** pure helpers avoid `sys.exit`; only `cli.py` exits.
- **Persistence:** each result is committed per file for crash durability.

## Testing notes

- Pure modules (`paths`, `scanning`, `database`) test against real temp dirs /
  in-memory data — no catalog needed.
- `test_cli.py` injects a **fake `CDMSDataCatalog`** into `sys.modules` so the
  CLI can be exercised end-to-end without the real client.
