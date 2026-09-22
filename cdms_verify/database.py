"""SQLite persistence layer for verification results.

Records each scanned file exactly once in a single ``verification_results``
table. The ``UNIQUE(file_path)`` constraint enforces the "record once" policy
at the database level. Files may be re-checked and updated in place via an
upsert. Run-level summary counts are not stored; they are derived on demand via
:func:`get_summary`.

Functions
---------
get_db
    Context manager yielding a configured SQLite connection.
connect_readonly
    Context manager yielding a read-only SQLite connection.
init_db
    Create the schema if it does not already exist.
upsert_result
    Insert or update a single file result, committing immediately.
get_verified_file_paths
    Return the subset of given paths already recorded as VERIFIED.
get_summary
    Return aggregate status counts across all recorded files.
get_verification_by_catalog_path
    Look up a file's verification record by catalog path (read-only).
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


@contextmanager
def connect_readonly(
    db_path: str | Path,
) -> Generator[sqlite3.Connection, None, None]:
    """Yield a read-only SQLite connection.

    Opens the database with ``mode=ro`` so it can never be modified, making it
    safe to run alongside the verification writer (WAL permits concurrent
    reads). The connection is always closed on exit.

    Parameters
    ----------
    db_path : str or pathlib.Path
        Path to an existing SQLite database file.

    Yields
    ------
    sqlite3.Connection
        A read-only connection whose ``row_factory`` is :class:`sqlite3.Row`.

    Notes
    -----
    Intended for consumers such as the cleanup tool that only read the
    database. Open one connection and reuse it across many lookups rather than
    opening one per call.

    Examples
    --------
    >>> with connect_readonly("verification.db") as conn:  # doctest: +SKIP
    ...     conn.execute("SELECT COUNT(*) FROM verification_results")
    """
    uri = f"file:{Path(db_path)}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def get_verification_by_catalog_path(
    conn: sqlite3.Connection,
    catalog_path: str,
) -> dict[str, Any] | None:
    """Look up a file's verification record by its catalog path.

    Parameters
    ----------
    conn : sqlite3.Connection
        An open (preferably read-only) connection, e.g. from
        :func:`connect_readonly`. The caller owns the connection's lifetime;
        pass one connection across many lookups rather than opening one per
        call.
    catalog_path : str
        The normalized CDMS catalog path to look up (e.g.
        ``/CDMS/SNOLAB/R1/Raw``).

    Returns
    -------
    dict or None
        A dict with ``status``, ``checksum``, ``size``, and ``mtime`` if a
        record exists, otherwise ``None``.

    Notes
    -----
    Matching is by ``catalog_path`` (machine-independent), not ``file_path``,
    so this works across machines whose local path prefixes differ.

    Examples
    --------
    >>> with connect_readonly("verification.db") as conn:  # doctest: +SKIP
    ...     rec = get_verification_by_catalog_path(conn, "/CDMS/SNOLAB/R1/Raw")
    """
    row = conn.execute(
        """
        SELECT status, checksum, size, mtime
        FROM verification_results
        WHERE catalog_path = ?
        """,
        (catalog_path,),
    ).fetchone()
    return dict(row) if row is not None else None


def get_verified_file_paths(
    db_path: str | Path,
    file_paths: list[str],
) -> set:
    """Return the subset of file paths already recorded as VERIFIED.

    Only ``VERIFIED`` files are considered "done" and skippable. Files recorded
    with any other status (``UNREGISTERED``, ``ERROR``) are intentionally
    excluded so the caller re-checks them.

    Parameters
    ----------
    db_path : str or pathlib.Path
        Path to the SQLite database file. Must already be initialized.
    file_paths : list of str
        The local file paths to check.

    Returns
    -------
    set of str
        The subset of ``file_paths`` recorded with status ``VERIFIED``.

    Examples
    --------
    >>> get_verified_file_paths("verification.db", ["/a", "/b"])  # doctest: +SKIP
    {'/a'}
    """
    if not file_paths:
        return set()

    placeholders = ",".join("?" for _ in file_paths)
    query = (
        f"SELECT file_path FROM verification_results "
        f"WHERE status = 'VERIFIED' AND file_path IN ({placeholders})"
    )
    with get_db(db_path) as conn:
        rows = conn.execute(query, tuple(file_paths)).fetchall()
    return {row["file_path"] for row in rows}


def upsert_result(
    conn: sqlite3.Connection,
    result: dict[str, Any],
    site: str,
) -> None:
    """Insert a file result, or update it if the file_path already exists.

    Uses SQLite's ``ON CONFLICT(file_path) DO UPDATE`` so a re-checked file's
    status, checksum, size, mtime, site, and scan timestamp are refreshed. The
    change is committed immediately for per-file durability.

    Parameters
    ----------
    conn : sqlite3.Connection
        An open connection (typically from :func:`get_db`).
    result : dict
        A single per-file row. Must contain ``file_path``, ``catalog_path``,
        ``status``, and ``checksum``, and may contain ``size`` and ``mtime``.
    site : str
        The catalog site that was queried, stored on the row.

    Notes
    -----
    Unlike :func:`insert_result`, this overwrites an existing row. It is used
    when re-checking non-terminal files (e.g. previously ``UNREGISTERED``) so a
    newly-registered file transitions to ``VERIFIED``.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        INSERT INTO verification_results
            (file_path, catalog_path, status, checksum,
             size, mtime, site, scan_timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_path) DO UPDATE SET
            catalog_path   = excluded.catalog_path,
            status         = excluded.status,
            checksum       = excluded.checksum,
            size           = excluded.size,
            mtime          = excluded.mtime,
            site           = excluded.site,
            scan_timestamp = excluded.scan_timestamp
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
    conn.commit()
