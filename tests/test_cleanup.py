"""Tests for cdms_verify.cleanup.

Covers the per-file deletion decision logic and the directory-level cleanup,
including the safety guarantee that only VERIFIED, checksum-matched files are
ever deleted — even in ``--delete`` mode.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from cdms_verify.cleanup import Decision, cleanup_directory, evaluate_file
from cdms_verify.database import connect_readonly, get_db, init_db

# --------------------------------------------------------------------------- #
# Helpers / fixtures
# --------------------------------------------------------------------------- #


def _make_file(base: Path, content: bytes, name: str = "file.dat") -> Path:
    """Create a CDMS-rooted file and return its path."""
    d = base / "CDMS" / "Raw" / "Run1"
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_bytes(content)
    return f


def _insert(db, catalog_path, status, checksum):
    """Insert a record as if written by a different machine.

    The stored file_path deliberately uses a foreign prefix to prove the
    cleanup matches on catalog_path, not file_path.
    """
    with get_db(db) as conn:
        conn.execute(
            "INSERT INTO verification_results "
            "(file_path, catalog_path, status, checksum, site, scan_timestamp) "
            "VALUES (?, ?, ?, ?, 'SLAC', '2024-01-01 00:00:00')",
            (f"/other/machine{catalog_path}", catalog_path, status, checksum),
        )


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@pytest.fixture
def db(tmp_path):
    """Return the path (as str) to a freshly initialized database."""
    path = tmp_path / "verification.db"
    init_db(path)
    return str(path)


# --------------------------------------------------------------------------- #
# evaluate_file — one decision per branch
# --------------------------------------------------------------------------- #


def test_delete_when_verified_and_matching(tmp_path, db):
    content = b"payload"
    f = _make_file(tmp_path, content)
    _insert(db, "/CDMS/Raw/Run1/file.dat", "VERIFIED", _sha(content))

    with connect_readonly(db) as conn:
        result = evaluate_file(str(f), conn)

    assert result.decision is Decision.DELETE
    assert result.catalog_path == "/CDMS/Raw/Run1/file.dat"


def test_keep_when_not_in_db(tmp_path, db):
    f = _make_file(tmp_path, b"payload")
    with connect_readonly(db) as conn:
        result = evaluate_file(str(f), conn)
    assert result.decision is Decision.KEEP_NOT_IN_DB


def test_keep_when_not_verified(tmp_path, db):
    content = b"payload"
    f = _make_file(tmp_path, content)
    _insert(db, "/CDMS/Raw/Run1/file.dat", "UNREGISTERED", _sha(content))
    with connect_readonly(db) as conn:
        result = evaluate_file(str(f), conn)
    assert result.decision is Decision.KEEP_NOT_VERIFIED


def test_keep_when_checksum_mismatch(tmp_path, db):
    f = _make_file(tmp_path, b"local content")
    _insert(db, "/CDMS/Raw/Run1/file.dat", "VERIFIED", "different_hash")
    with connect_readonly(db) as conn:
        result = evaluate_file(str(f), conn)
    assert result.decision is Decision.KEEP_CHECKSUM_MISMATCH


def test_keep_when_no_cdms_component(tmp_path, db):
    """A file outside any CDMS path cannot derive a catalog path."""
    outside = tmp_path / "not_cdms" / "file.dat"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"data")
    with connect_readonly(db) as conn:
        result = evaluate_file(str(outside), conn)
    assert result.decision is Decision.KEEP_LOCAL_ERROR
    assert result.catalog_path is None


def test_matches_on_catalog_path_not_file_path(tmp_path, db):
    """The stored file_path uses a foreign prefix; matching must still work."""
    content = b"payload"
    f = _make_file(tmp_path, content)
    # Note _insert stores file_path as /other/machine/CDMS/... — different
    # from this machine's tmp_path-based location.
    _insert(db, "/CDMS/Raw/Run1/file.dat", "VERIFIED", _sha(content))
    with connect_readonly(db) as conn:
        result = evaluate_file(str(f), conn)
    assert result.decision is Decision.DELETE


# --------------------------------------------------------------------------- #
# cleanup_directory — dry-run vs. delete
# --------------------------------------------------------------------------- #


def test_dry_run_does_not_delete(tmp_path, db):
    content = b"payload"
    f = _make_file(tmp_path, content)
    _insert(db, "/CDMS/Raw/Run1/file.dat", "VERIFIED", _sha(content))

    results = cleanup_directory(tmp_path / "CDMS", db, recursive=True, delete=False)

    assert any(r.decision is Decision.DELETE for r in results)
    assert f.exists()  # dry-run: file still present


def test_delete_removes_eligible_file(tmp_path, db):
    content = b"payload"
    f = _make_file(tmp_path, content)
    _insert(db, "/CDMS/Raw/Run1/file.dat", "VERIFIED", _sha(content))

    cleanup_directory(tmp_path / "CDMS", db, recursive=True, delete=True)

    assert not f.exists()  # actually deleted


def test_delete_keeps_mismatched_file(tmp_path, db):
    """A checksum mismatch is never deleted, even in --delete mode."""
    f = _make_file(tmp_path, b"local content")
    _insert(db, "/CDMS/Raw/Run1/file.dat", "VERIFIED", "wrong_hash")

    cleanup_directory(tmp_path / "CDMS", db, recursive=True, delete=True)

    assert f.exists()  # kept because checksum did not match


def test_delete_keeps_unverified_file(tmp_path, db):
    """A non-VERIFIED status is never deleted, even in --delete mode."""
    content = b"payload"
    f = _make_file(tmp_path, content)
    _insert(db, "/CDMS/Raw/Run1/file.dat", "UNREGISTERED", _sha(content))

    cleanup_directory(tmp_path / "CDMS", db, recursive=True, delete=True)

    assert f.exists()


def test_delete_keeps_file_not_in_db(tmp_path, db):
    """A file with no DB record is never deleted."""
    f = _make_file(tmp_path, b"payload")

    cleanup_directory(tmp_path / "CDMS", db, recursive=True, delete=True)

    assert f.exists()


def test_mixed_directory(tmp_path, db):
    """A directory with several files yields the right per-file decisions."""
    good = _make_file(tmp_path, b"good", name="good.dat")
    bad = _make_file(tmp_path, b"bad-local", name="bad.dat")
    absent = _make_file(tmp_path, b"absent", name="absent.dat")

    _insert(db, "/CDMS/Raw/Run1/good.dat", "VERIFIED", _sha(b"good"))
    _insert(db, "/CDMS/Raw/Run1/bad.dat", "VERIFIED", "mismatch_hash")
    # absent.dat intentionally not inserted

    results = cleanup_directory(tmp_path / "CDMS", db, recursive=True, delete=True)
    by_name = {Path(r.local_path).name: r.decision for r in results}

    assert by_name["good.dat"] is Decision.DELETE
    assert by_name["bad.dat"] is Decision.KEEP_CHECKSUM_MISMATCH
    assert by_name["absent.dat"] is Decision.KEEP_NOT_IN_DB

    assert not good.exists()  # only the good file was removed
    assert bad.exists()
    assert absent.exists()


def test_nonrecursive_ignores_subdirs(tmp_path, db):
    """--no-recursive only evaluates the top level of the given directory."""
    root = tmp_path / "CDMS"
    root.mkdir()
    top = root / "top.dat"
    top.write_bytes(b"top")
    sub = root / "Sub"
    sub.mkdir()
    nested = sub / "nested.dat"
    nested.write_bytes(b"nested")

    _insert(db, "/CDMS/top.dat", "VERIFIED", _sha(b"top"))
    _insert(db, "/CDMS/Sub/nested.dat", "VERIFIED", _sha(b"nested"))

    cleanup_directory(root, db, recursive=False, delete=True)

    assert not top.exists()  # top-level file deleted
    assert nested.exists()  # nested file untouched
