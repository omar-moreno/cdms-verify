"""Tests for cdms_verify.database.

Covers the single-table results schema: bulk and incremental inserts, the
``UNIQUE(file_path)`` "record once" guarantee, existence lookups, derived
summary counts, and durability of incrementally-committed rows.

"""

from __future__ import annotations

import pytest

from cdms_verify.database import (
    connect_readonly,
    get_db,
    get_summary,
    get_verification_by_catalog_path,
    get_verified_file_paths,
    init_db,
    upsert_result,
)

# --------------------------------------------------------------------------- #
# Helpers / fixtures
# --------------------------------------------------------------------------- #


def _row(
    path: str,
    status: str = "VERIFIED",
    checksum: str = "abc",
    size: int = 100,
    mtime: float = 1700000000.0,
) -> dict:
    """Build a minimal, valid result row for tests."""
    return {
        "file_path": path,
        "catalog_path": f"/CDMS{path}",
        "status": status,
        "checksum": checksum,
        "size": size,
        "mtime": mtime,
    }


def _seed(db_path, rows, site: str = "SLAC") -> None:
    """Insert result rows directly for test setup.

    Uses direct SQL rather than a production function so tests do not depend on
    the production write path.
    """
    ts = "2024-01-01 00:00:00"
    with get_db(db_path) as conn:
        conn.executemany(
            "INSERT INTO verification_results "
            "(file_path, catalog_path, status, checksum, size, mtime, site, "
            "scan_timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    r["file_path"],
                    r["catalog_path"],
                    r["status"],
                    r["checksum"],
                    r.get("size"),
                    r.get("mtime"),
                    site,
                    ts,
                )
                for r in rows
            ],
        )


@pytest.fixture
def db(tmp_path):
    """Return the path to a freshly initialized database file."""
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _count(db_path) -> int:
    """Return the number of rows currently in verification_results."""
    with get_db(db_path) as conn:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM verification_results"
        ).fetchone()["n"]


# --------------------------------------------------------------------------- #
# init_db
# --------------------------------------------------------------------------- #


def test_init_db_is_idempotent(tmp_path):
    """Calling init_db repeatedly does not error or drop data."""
    path = tmp_path / "test.db"
    init_db(path)
    _seed(path, [_row("/a")])
    init_db(path)
    assert _count(path) == 1


def test_init_db_creates_expected_columns(db):
    """The results table exposes all expected columns."""
    with get_db(db) as conn:
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(verification_results)")
        }
    assert cols == {
        "id",
        "file_path",
        "catalog_path",
        "status",
        "checksum",
        "size",
        "mtime",
        "site",
        "scan_timestamp",
    }


# --------------------------------------------------------------------------- #
# upsert_result
# --------------------------------------------------------------------------- #


def test_upsert_result_inserts_and_commits(db):
    """upsert_result inserts a brand-new file and commits it."""
    with get_db(db) as conn:
        upsert_result(conn, _row("/a"), "SLAC")
    assert _count(db) == 1


def test_upsert_commits_immediately(db):
    """The row is durable after upsert (committed, not just buffered)."""
    with get_db(db) as conn:
        upsert_result(conn, _row("/a"), "SLAC")
    # Fresh connection proves the write was committed.
    with get_db(db) as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM verification_results").fetchone()[
            "n"
        ]
    assert n == 1


def test_upsert_updates_existing_row(db):
    """An UNREGISTERED file upserted as VERIFIED updates in place."""
    _seed(db, [_row("/a", status="UNREGISTERED", checksum="old", size=1, mtime=1.0)])
    assert get_summary(db)["unregistered"] == 1

    with get_db(db) as conn:
        upsert_result(
            conn,
            _row("/a", status="VERIFIED", checksum="new", size=2, mtime=2.0),
            "SLAC",
        )

    summary = get_summary(db)
    assert summary["registered"] == 1
    assert summary["unregistered"] == 0
    assert _count(db) == 1  # updated, not duplicated

    with get_db(db) as conn:
        row = conn.execute(
            "SELECT status, checksum, size FROM verification_results "
            "WHERE file_path = '/a'"
        ).fetchone()
    assert row["status"] == "VERIFIED"
    assert row["checksum"] == "new"
    assert row["size"] == 2


def test_upsert_handles_none_size_and_mtime(db):
    """None size/mtime (unstat-able file) are stored as NULL."""
    row = _row("/a")
    row["size"] = None
    row["mtime"] = None
    with get_db(db) as conn:
        upsert_result(conn, row, "SLAC")
    with get_db(db) as conn:
        stored = conn.execute(
            "SELECT size, mtime FROM verification_results WHERE file_path = '/a'"
        ).fetchone()
    assert stored["size"] is None
    assert stored["mtime"] is None


def test_upsert_stores_site(db):
    with get_db(db) as conn:
        upsert_result(conn, _row("/a"), "CUTE")
    with get_db(db) as conn:
        row = conn.execute(
            "SELECT site FROM verification_results WHERE file_path = '/a'"
        ).fetchone()
    assert row["site"] == "CUTE"


def test_partial_progress_survives_exception(db):
    """Rows committed before an error remain in the database."""

    def fail_after_two():
        with get_db(db) as conn:
            upsert_result(conn, _row("/a"), "SLAC")
            upsert_result(conn, _row("/b"), "SLAC")
            raise RuntimeError("simulated crash")

    with pytest.raises(RuntimeError):
        fail_after_two()

    with get_db(db) as conn:
        paths = {
            r["file_path"]
            for r in conn.execute("SELECT file_path FROM verification_results")
        }
    assert paths == {"/a", "/b"}


# --------------------------------------------------------------------------- #
# get_verified_file_paths
# --------------------------------------------------------------------------- #


def test_get_verified_file_paths_only_returns_verified(db):
    """Only VERIFIED files are reported as skippable."""
    _seed(
        db,
        [
            _row("/a", status="VERIFIED"),
            _row("/b", status="UNREGISTERED"),
            _row(
                "/c",
                status="ERROR",
                checksum="ERROR_CALCULATING",
                size=None,
                mtime=None,
            ),
        ],
    )
    assert get_verified_file_paths(db, ["/a", "/b", "/c"]) == {"/a"}


def test_get_verified_file_paths_empty_input(db):
    assert get_verified_file_paths(db, []) == set()


def test_get_verified_file_paths_none_verified(db):
    _seed(db, [_row("/a", status="UNREGISTERED")])
    assert get_verified_file_paths(db, ["/a"]) == set()


def test_get_verified_file_paths_ignores_unlisted(db):
    _seed(db, [_row("/a", status="VERIFIED")])
    assert get_verified_file_paths(db, ["/b", "/c"]) == set()


# --------------------------------------------------------------------------- #
# get_summary
# --------------------------------------------------------------------------- #


def test_get_summary_empty_db(db):
    assert get_summary(db) == {
        "total": 0,
        "registered": 0,
        "unregistered": 0,
        "errors": 0,
    }


def test_get_summary_counts_by_status(db):
    _seed(
        db,
        [
            _row("/a", status="VERIFIED"),
            _row("/b", status="VERIFIED"),
            _row("/c", status="UNREGISTERED"),
            _row("/d", status="ERROR"),
        ],
    )
    assert get_summary(db) == {
        "total": 4,
        "registered": 2,
        "unregistered": 1,
        "errors": 1,
    }


def test_get_summary_reflects_upserts(db):
    with get_db(db) as conn:
        upsert_result(conn, _row("/a", status="VERIFIED"), "SLAC")
        upsert_result(conn, _row("/b", status="ERROR"), "SLAC")
    assert get_summary(db) == {
        "total": 2,
        "registered": 1,
        "unregistered": 0,
        "errors": 1,
    }


# --------------------------------------------------------------------------- #
# get_verification_by_catalog_path
# --------------------------------------------------------------------------- #


def test_get_verification_by_catalog_path_found(db):
    _seed(db, [_row("/a", status="VERIFIED", checksum="abc")])
    with connect_readonly(db) as conn:
        rec = get_verification_by_catalog_path(conn, "/CDMS/a")
    assert rec is not None
    assert rec["status"] == "VERIFIED"
    assert rec["checksum"] == "abc"


def test_get_verification_by_catalog_path_missing(db):
    with connect_readonly(db) as conn:
        assert get_verification_by_catalog_path(conn, "/CDMS/nope") is None


def test_get_verification_by_catalog_path_returns_all_fields(db):
    _seed(db, [_row("/a", size=4096, mtime=1712345678.5)])
    with connect_readonly(db) as conn:
        rec = get_verification_by_catalog_path(conn, "/CDMS/a")
    assert set(rec.keys()) == {"status", "checksum", "size", "mtime"}
    assert rec["size"] == 4096
    assert rec["mtime"] == 1712345678.5
