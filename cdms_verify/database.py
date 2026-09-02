"""SQLite persistence layer for verification results.

Records each scanned file exactly once in a single ``verification_results``
table. The ``UNIQUE(file_path)`` constraint enforces the "record once" policy
at the database level, so re-inserting a known file is a no-op. Run-level
summary counts are not stored; they are derived on demand via
:func:`get_summary`.

Functions
---------
get_db
    Context manager yielding a configured SQLite connection.
init_db
    Create the schema if it does not already exist.
save_results
    Insert new file results (idempotent per file_path).
get_known_file_paths
    Return the subset of given paths already recorded.
get_summary
    Return aggregate status counts across all recorded files.
insert_result
    Insert one file result on an existing connection and commit it.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any

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
def get_db(db_path: str | Path) -> Generator[sqlite3.Connection, None, None]:
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


def init_db(db_path: str | Path) -> None:
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
    with get_db(db_path) as conn:
        conn.executescript(_load_schema())


def save_results(
    db_path: str | Path,
    results: list[dict[str, Any]],
    site: str,
) -> int:
    """Insert new file results, ignoring any whose file_path already exists.

    Uses ``INSERT OR IGNORE`` so the ``UNIQUE(file_path)`` constraint makes
    re-insertion of a known file a silent no-op. This guarantees each file is
    recorded exactly once even if the caller's skip logic is bypassed.

    Parameters
    ----------
    db_path : str or pathlib.Path
        Path to the SQLite database file. Must already be initialized.
    results : list of dict
        Per-file rows. Each dict must contain ``file_path``, ``catalog_path``,
        ``status``, and ``checksum``, and may contain ``size`` (int or None)
        and ``mtime`` (float or None).
    site : str
        The catalog site that was queried, stored on each new row.

    Returns
    -------
    int
        The number of rows actually inserted (excludes ignored duplicates).

    Examples
    --------
    >>> save_results("verification.db", results, "SLAC")  # doctest: +SKIP
    3

    """
    if not results:
        return 0

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with get_db(db_path) as conn:
        cursor = conn.executemany(
            """
            INSERT OR IGNORE INTO verification_results
                (file_path, catalog_path, status, checksum,
                 size, mtime, site, scan_timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r["file_path"],
                    r["catalog_path"],
                    r["status"],
                    r["checksum"],
                    r.get("size"),
                    r.get("mtime"),
                    site,
                    timestamp,
                )
                for r in results
            ],
        )
        return cursor.rowcount


def get_known_file_paths(
    db_path: str | Path,
    file_paths: list[str],
) -> set:
    """Return the subset of file paths already recorded in the database.

    A file "exists in the database" if it appears in any prior
    ``verification_results`` row, regardless of that row's status.

    Parameters
    ----------
    db_path : str or pathlib.Path
        Path to the SQLite database file. Must already be initialized.
    file_paths : list of str
        The local file paths to check for prior existence.

    Returns
    -------
    set of str
        The subset of ``file_paths`` that already appear in the database.

    Notes
    -----
    Existence is keyed on ``file_path`` alone. No checksum, size, or mtime
    comparison is performed; a file that was recorded in any previous run is
    considered known.

    Examples
    --------
    >>> get_known_file_paths(
    ...     "verification.db", ["/data/a.dat", "/data/b.dat"]
    ... )  # doctest: +SKIP
    {'/data/a.dat'}
    """
    if not file_paths:
        return set()

    placeholders = ",".join("?" for _ in file_paths)
    query = (
        f"SELECT file_path FROM verification_results "
        f"WHERE file_path IN ({placeholders})"
    )
    with get_db(db_path) as conn:
        rows = conn.execute(query, tuple(file_paths)).fetchall()
    return {row["file_path"] for row in rows}


def get_summary(db_path: str | Path) -> dict[str, int]:
    """Return aggregate status counts across all recorded files.

    Parameters
    ----------
    db_path : str or pathlib.Path
        Path to the SQLite database file.

    Returns
    -------
    dict of str to int
        A dict with ``total``, ``registered``, ``unregistered``, and
        ``errors`` computed from the current table contents.

    Notes
    -----
    These counts are derived on demand rather than stored, so they can never
    drift from the underlying rows.
    """
    query = """
        SELECT
            COUNT(*)                          AS total,
            SUM(status = 'VERIFIED')          AS registered,
            SUM(status = 'UNREGISTERED')      AS unregistered,
            SUM(status = 'ERROR')             AS errors
        FROM verification_results
    """
    with get_db(db_path) as conn:
        row = conn.execute(query).fetchone()
    return {
        "total": row["total"] or 0,
        "registered": row["registered"] or 0,
        "unregistered": row["unregistered"] or 0,
        "errors": row["errors"] or 0,
    }


def insert_result(
    conn: sqlite3.Connection,
    result: dict[str, Any],
    site: str,
) -> bool:
    """Insert one file result on an existing connection and commit it.

    Uses ``INSERT OR IGNORE`` so a file whose ``file_path`` already exists is
    silently skipped. The insert is committed immediately, making each row
    durable the moment it is processed — so an interruption mid-scan does not
    lose files already handled.

    Parameters
    ----------
    conn : sqlite3.Connection
        An open connection (typically obtained from :func:`get_db`).
    result : dict
        A single per-file row. Must contain ``file_path``, ``catalog_path``,
        ``status``, and ``checksum``, and may contain ``size`` (int or None)
        and ``mtime`` (float or None).
    site : str
        The catalog site that was queried, stored on the new row.

    Returns
    -------
    bool
        ``True`` if a row was inserted, ``False`` if it was ignored because
        the ``file_path`` already existed.

    Notes
    -----
    A ``scan_timestamp`` is generated per call, so incrementally-inserted rows
    carry the time each file was actually recorded rather than a single
    run-wide timestamp.

    Examples
    --------
    >>> with get_db("verification.db") as conn:  # doctest: +SKIP
    ...     insert_result(conn, row, "SLAC")
    True
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO verification_results
            (file_path, catalog_path, status, checksum,
             size, mtime, site, scan_timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            result["file_path"],
            result["catalog_path"],
            result["status"],
            result["checksum"],
            result.get("size"),
            result.get("mtime"),
            site,
            timestamp,
        ),
    )
    # Commit immediately so this row survives a subsequent crash.
    conn.commit()
    return cursor.rowcount > 0
