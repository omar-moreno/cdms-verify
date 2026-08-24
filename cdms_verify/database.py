"""SQLite persistence layer for verification results.

Stores each execution of the verification tool as a row in
``verification_runs`` together with one ``verification_results`` row per
scanned file. This historical design allows trends to be queried over time
(e.g. "was this file registered last week but missing now?").

The schema is defined in the sibling ``schema.sql`` file and applied
idempotently by :func:`init_db`.

Functions
---------
get_db
    Context manager yielding a configured SQLite connection.
init_db
    Create the schema if it does not already exist.
save_results_to_db
    Persist a verification run and its per-file results.

Notes
-----
SQLite is used for its zero-dependency, single-file nature which suits
reproducible k8s deployments. Write-Ahead Logging (WAL) is enabled to allow
concurrent reads during writes; however, SQLite still serializes writers, so
multiple pods should not write to the *same* database file simultaneously.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from importlib import resources
from typing import Any, Dict, Generator, List, Union

from pathlib import Path

#: Location of the packaged schema, loaded via importlib.resources.
_SCHEMA_RESOURCE = "schema.sql"


def _load_schema() -> str:
    """Load the packaged SQL schema as a string.

    Returns
    -------
    str
        The full contents of ``schema.sql`` bundled with the package.

    Notes
    -----
    Uses :mod:`importlib.resources` so the schema is located correctly whether
    the package is run from source, an installed wheel, or a zipapp.
    """
    return (
        resources.files("cdms_verify")
        .joinpath(_SCHEMA_RESOURCE)
        .read_text(encoding="utf-8")
    )


@contextmanager
def get_db(db_path: Union[str, Path]) -> Generator[sqlite3.Connection, None, None]:
    """Yield a configured SQLite connection with transactional semantics.

    The connection is configured with WAL journaling and enforced foreign
    keys. On normal exit the transaction is committed; on any exception it is
    rolled back and the exception is re-raised. The connection is always
    closed.

    Parameters
    ----------
    db_path : str or pathlib.Path
        Path to the SQLite database file. Created if it does not exist.

    Yields
    ------
    sqlite3.Connection
        An open connection whose ``row_factory`` is set to
        :class:`sqlite3.Row` for dict-like row access.

    Raises
    ------
    Exception
        Any exception raised within the ``with`` block is propagated after the
        transaction is rolled back.

    Examples
    --------
    >>> with get_db(":memory:") as conn:  # doctest: +SKIP
    ...     conn.execute("SELECT 1")
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Union[str, Path]) -> None:
    """Create the database schema if it does not already exist.

    Parameters
    ----------
    db_path : str or pathlib.Path
        Path to the SQLite database file to initialize.


    Notes
    -----
    Safe to call repeatedly; all statements in the schema use
    ``CREATE ... IF NOT EXISTS``.

    Examples
    --------
    >>> init_db("verification.db")  # doctest: +SKIP
    """
    schema = _load_schema()
    with get_db(db_path) as conn:
        conn.executescript(schema)


def save_results_to_db(
    db_path: Union[str, Path],
    results: List[Dict[str, Any]],
    stats: Dict[str, int],
    local_dir: str,
    catalog_path: str,
    site: str,
) -> int:
    """Persist a verification run and its per-file results.

    Inserts a single row into ``verification_runs`` capturing the run-level
    summary, then bulk-inserts one row per file into ``verification_results``
    linked by the new run's id.

    Parameters
    ----------
    db_path : str or pathlib.Path
        Path to the SQLite database file. Must already be initialized via
        :func:`init_db`.
    results : list of dict
        Per-file result rows. Each dict must contain the keys ``file_path``,
        ``catalog_path``, ``status``, and ``checksum``, and may contain
        ``size`` (int or None) and ``mtime`` (float or None). Missing size or
        mtime keys are stored as ``NULL``.
    stats : dict of str to int
        Run-level summary containing the keys ``total``, ``registered``,
        ``unregistered``, ``errors``m and ``changed``. ``changed`` defaults to
        ``0`` if absent.
    local_dir : str
        The local directory that was scanned, stored for provenance.
    catalog_path : str
        The catalog path prefix that was verified against.
    site : str
        The storage site the run targeted.

    Returns
    -------
    int
        The autogenerated ``id`` of the inserted ``verification_runs`` row.

    Examples
    --------
    >>> run_id = save_results_to_db(  # doctest: +SKIP
    ...     "verification.db", results, stats,
    ...     "/data/CDMS/Raw", "/CDMS/Raw", "SLAC",
    ... )
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with get_db(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO verification_runs
                (run_timestamp, local_dir, catalog_path, site,
                 total, registered, unregistered, errors, changed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                local_dir,
                catalog_path,
                site,
                stats["total"],
                stats["registered"],
                stats["unregistered"],
                stats["errors"],
                stats.get("changed", 0),
            ),
        )
        run_id = cursor.lastrowid

        conn.executemany(
            """
            INSERT INTO verification_results
                (run_id, file_path, catalog_path, status, checksum, size, mtime)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id,
                    r["file_path"],
                    r["catalog_path"],
                    r["status"],
                    r["checksum"],
                    r.get("size"),
                    r.get("mtime"),
                )
                for r in results
            ],
        )

    return run_id

def get_existing_file_info(
    db_path: Union[str, Path],
    file_paths: List[str],
) -> Dict[str, Dict[str, Any]]:
    """Return the most recent stored checksum, size, and mtime per file path.

    For every requested ``file_path``, returns the record from the most recent
    run in which that file appeared with a usable checksum.

    Parameters
    ----------
    db_path : str or pathlib.Path
        Path to the SQLite database file. Must already be initialized.
    file_paths : list of str
        The local file paths to look up.

    Returns
    -------
    dict of str to dict
        A mapping from ``file_path`` to a record dict with keys ``checksum``,
        ``size``, and ``mtime``. File paths with no usable prior record are
        omitted from the mapping.

    Notes
    -----
    Rows whose checksum is ``NULL``, empty, or equal to the error sentinel
    ``ERROR_CALCULATING`` are ignored so that a previously failed checksum is
    retried rather than reused. The returned ``size`` and ``mtime`` allow a
    caller to decide whether the cached checksum is still trustworthy.

    Examples
    --------
    >>> get_existing_file_info("verification.db", ["/data/a.dat"])  # doctest: +SKIP
    {'/data/a.dat': { 'checksum': 'abc123...', 'size': 1024, 'mtime': 170000000.0}}
    """
    if not file_paths:
        return {}

    placeholders = ",".join("?" for _ in file_paths)
    # For each file_path, pick the checksum from the highest (latest) run_id.
    query = f"""
        SELECT r.file_path, r.checksum, r.size, r.mtime
        FROM verification_results AS r
        JOIN (
            SELECT file_path, MAX(run_id) AS max_run
            FROM verification_results
            WHERE file_path IN ({placeholders})
              AND checksum IS NOT NULL
              AND checksum != ''
              AND checksum != 'ERROR_CALCULATING'
            GROUP BY file_path
        ) AS latest
          ON r.file_path = latest.file_path
         AND r.run_id = latest.max_run
    """

    with get_db(db_path) as conn:
        rows = conn.execute(query, tuple(file_paths)).fetchall()

    return {row["file_path"]: { 
                "checksum": row["checksum"],
                "size": row["size"],
                "mtime": row["mtime"],
            }
            for row in rows
    }

def load_run(
    db_path: Union[str, Path],
    run_id: int,
) -> Dict[str, Any]:
    """Load a single verification run and its results from the database.

    Parameters
    ----------
    db_path : str or pathlib.Path
        Path to the SQLite database file.
    run_id : int
        The identifier of the run to load, as returned by
        :func:`save_results_to_db`.

    Returns
    -------
    dict
        A dictionary with two keys:

        ``stats``
            A dict with ``total``, ``registered``, ``unregistered``,
            ``errors``, and ``changed`` plus run metadata (``run_timestamp``,
            ``local_dir``, ``catalog_path``, ``site``).
        ``results``
            A list of per-file dicts with ``file_path``, ``catalog_path``,
            ``status``, ``checksum``, ``size`` and ``mtime``. 

    Raises
    ------
    KeyError
        If no run with the given ``run_id`` exists.

    Examples
    --------
    >>> data = load_run("verification.db", 1)  # doctest: +SKIP
    >>> data["stats"]["total"]  # doctest: +SKIP
    42
    """
    with get_db(db_path) as conn:
        run_row = conn.execute(
            "SELECT * FROM verification_runs WHERE id = ?", (run_id,)
        ).fetchone()

        if run_row is None:
            raise KeyError(f"No verification run with id={run_id}")

        result_rows = conn.execute(
            """
            SELECT file_path, catalog_path, status, checksum, size, mtime
            FROM verification_results
            WHERE run_id = ?
            ORDER BY id
            """,
            (run_id,),
        ).fetchall()

    stats = {
        "total": run_row["total"],
        "registered": run_row["registered"],
        "unregistered": run_row["unregistered"],
        "errors": run_row["errors"],
        "changed": run_row["changed"],
        "run_timestamp": run_row["run_timestamp"],
        "local_dir": run_row["local_dir"],
        "catalog_path": run_row["catalog_path"],
        "site": run_row["site"],
    }
    results = [dict(row) for row in result_rows]

    return {"stats": stats, "results": results}
