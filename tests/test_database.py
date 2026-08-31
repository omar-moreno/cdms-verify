"""Tests for cdms_verify.database.

Covers the single-table results schema: bulk and incremental inserts, the
``UNIQUE(file_path)`` "record once" guarantee, existence lookups, derived
summary counts, and durability of incrementally-committed rows.

"""

from __future__ import annotations

import pytest

from cdms_verify.database import (
    get_db,
    get_known_file_paths,
    get_summary,
    init_db,
    insert_result,
    save_results,
)

# --------------------------------------------------------------------------- #
# Helpers / fixtures
# --------------------------------------------------------------------------- #

def _row(path: str, status: str = "VERIFIED", checksum: str = "abc",
         size: int = 100, mtime: float = 1700000000.0) -> dict:
    """Build a minimal, valid result row for tests."""
    return {
        "file_path": path,
        "catalog_path": f"/CDMS{path}",
        "status": status,
        "checksum": checksum,
        "size": size,
        "mtime": mtime,
    }


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
    with get_db(path) as conn:
        conn.execute(
            "INSERT INTO verification_results "
            "(file_path, catalog_path, status, checksum, site, scan_timestamp) "
            "VALUES ('/a', '/CDMS/a', 'VERIFIED', 'abc', 'SLAC', '2024-01-01 00:00:00')"
        )
    # Second init must not wipe the existing row.
    init_db(path)
    assert _count(path) == 1


def test_init_db_creates_expected_columns(db):
    """The results table exposes all expected columns."""
    with get_db(db) as conn:
        cols = {row["name"] for row in conn.execute(
            "PRAGMA table_info(verification_results)"
        )}
    assert cols == {
        "id", "file_path", "catalog_path", "status", "checksum",
        "size", "mtime", "site", "scan_timestamp",
    }


# --------------------------------------------------------------------------- #
# save_results (bulk)
# --------------------------------------------------------------------------- #

def test_save_results_inserts_all_new(db):
    inserted = save_results(db, [_row("/a"), _row("/b")], site="SLAC")
    assert inserted == 2
    assert _count(db) == 2


def test_save_results_empty_list_is_noop(db):
    assert save_results(db, [], site="SLAC") == 0
    assert _count(db) == 0


def test_save_results_persists_size_and_mtime(db):
    save_results(db, [_row("/a", size=4096, mtime=1712345678.5)], site="SLAC")
    with get_db(db) as conn:
        row = conn.execute(
            "SELECT size, mtime FROM verification_results WHERE file_path = '/a'"
        ).fetchone()
    assert row["size"] == 4096
    assert row["mtime"] == 1712345678.5


def test_save_results_persists_site(db):
    save_results(db, [_row("/a")], site="CUTE")
    with get_db(db) as conn:
        row = conn.execute(
            "SELECT site FROM verification_results WHERE file_path = '/a'"
        ).fetchone()
    assert row["site"] == "CUTE"


def test_save_results_ignores_duplicates(db):
    """UNIQUE(file_path) makes re-inserting a known path a no-op."""
    assert save_results(db, [_row("/a")], site="SLAC") == 1
    # Same path again, even with different content, is ignored.
    assert save_results(db, [_row("/a", status="UNREGISTERED", checksum="zzz")],
                        site="SLAC") == 0
    assert _count(db) == 1
    # The original row is unchanged (INSERT OR IGNORE, not REPLACE).
    with get_db(db) as conn:
        row = conn.execute(
            "SELECT status, checksum FROM verification_results WHERE file_path = '/a'"
        ).fetchone()
    assert row["status"] == "VERIFIED"
    assert row["checksum"] == "abc"


def test_save_results_mixed_new_and_duplicate(db):
    save_results(db, [_row("/a")], site="SLAC")
    inserted = save_results(db, [_row("/a"), _row("/b"), _row("/c")], site="SLAC")
    assert inserted == 2          # only /b and /c are new
    assert _count(db) == 3


# --------------------------------------------------------------------------- #
# insert_result (incremental)
# --------------------------------------------------------------------------- #

def test_insert_result_inserts_and_commits(db):
    """insert_result persists a row immediately and reports insertion."""
    with get_db(db) as conn:
        assert insert_result(conn, _row("/a"), "SLAC") is True

    # Re-open a fresh connection to prove the row was committed, not just
    # buffered in the previous transaction.
    assert _count(db) == 1


def test_insert_result_ignores_duplicate(db):
    """A second insert of the same file_path is a no-op returning False."""
    with get_db(db) as conn:
        assert insert_result(conn, _row("/a"), "SLAC") is True
        assert insert_result(conn, _row("/a"), "SLAC") is False
    assert _count(db) == 1


def test_insert_result_handles_none_size_and_mtime(db):
    """None size/mtime (unstat-able file) are stored as NULL."""
    row = _row("/a")
    row["size"] = None
    row["mtime"] = None
    with get_db(db) as conn:
        assert insert_result(conn, row, "SLAC") is True
    with get_db(db) as conn:
        stored = conn.execute(
            "SELECT size, mtime FROM verification_results WHERE file_path = '/a'"
        ).fetchone()
    assert stored["size"] is None
    assert stored["mtime"] is None


def test_partial_progress_survives_exception(db):
    """Rows committed before an error remain in the database."""
    def fail_after_two():
        with get_db(db) as conn:
            insert_result(conn, _row("/a"), "SLAC")
            insert_result(conn, _row("/b"), "SLAC")
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
# get_known_file_paths
# --------------------------------------------------------------------------- #

def test_get_known_file_paths_returns_only_known(db):
    save_results(db, [_row("/a")], site="SLAC")
    known = get_known_file_paths(db, ["/a", "/b", "/c"])
    assert known == {"/a"}


def test_get_known_file_paths_empty_input(db):
    assert get_known_file_paths(db, []) == set()


def test_get_known_file_paths_ignores_status(db):
    """A file is 'known' regardless of the status it was recorded with."""
    save_results(db, [_row("/x", status="UNREGISTERED")], site="SLAC")
    assert get_known_file_paths(db, ["/x"]) == {"/x"}


def test_get_known_file_paths_none_known(db):
    save_results(db, [_row("/a")], site="SLAC")
    assert get_known_file_paths(db, ["/b", "/c"]) == set()


# --------------------------------------------------------------------------- #
# get_summary
# --------------------------------------------------------------------------- #

def test_get_summary_empty_db(db):
    assert get_summary(db) == {
        "total": 0, "registered": 0, "unregistered": 0, "errors": 0,
    }


def test_get_summary_counts_by_status(db):
    save_results(
        db,
        [
            _row("/a", status="VERIFIED"),
            _row("/b", status="VERIFIED"),
            _row("/c", status="UNREGISTERED"),
            _row("/d", status="ERROR"),
        ],
        site="SLAC",
    )
    assert get_summary(db) == {
        "total": 4, "registered": 2, "unregistered": 1, "errors": 1,
    }


def test_get_summary_reflects_incremental_inserts(db):
    with get_db(db) as conn:
        insert_result(conn, _row("/a", status="VERIFIED"), "SLAC")
        insert_result(conn, _row("/b", status="ERROR"), "SLAC")
    assert get_summary(db) == {
        "total": 2, "registered": 1, "unregistered": 0, "errors": 1,
    }
