"""End-to-end tests for cdms_verify.cli.

The CLI imports ``CDMSDataCatalog`` at module load time and queries it at
runtime. We inject a fake catalog module into ``sys.modules`` before importing
the CLI, and use Click's ``CliRunner`` to invoke the command and capture its
exit code and output.
"""

from __future__ import annotations

import hashlib
import sys
import types
from pathlib import Path

import pytest
from click.testing import CliRunner

from cdms_verify.database import get_db, get_summary, init_db


# --------------------------------------------------------------------------- #
# Fake CDMSDataCatalog injected before importing the CLI
# --------------------------------------------------------------------------- #

class _FakeDataset:
    """Minimal dataset object exposing the .path attribute the CLI reads."""

    def __init__(self, path: str):
        self.path = path


class _FakeClient:
    """Fake catalog client whose search results are configurable per test."""

    #: Class-level list of catalog paths to report as "registered".
    registered_paths: list = []

    def search(self, path, site="All"):
        # The CLI calls search(path) and search(path + "**"); return the
        # configured paths on the first call and nothing on the recursive one
        # to avoid double-counting. We simply return everything on the base
        # call and an empty list for the "**" call.
        if path.endswith("**"):
            return []
        return [_FakeDataset(p) for p in _FakeClient.registered_paths]


class _FakeCatalog:
    """Fake CDMSDataCatalog exposing a .client attribute."""

    def __init__(self):
        self.client = _FakeClient()


@pytest.fixture(autouse=True)
def fake_catalog_module(monkeypatch):
    """Install a fake CDMSDataCatalog module and reset registered paths.

    Autouse so every test in this module runs with the fake catalog in place.
    """
    fake_module = types.ModuleType("CDMSDataCatalog")
    fake_module.CDMSDataCatalog = _FakeCatalog
    monkeypatch.setitem(sys.modules, "CDMSDataCatalog", fake_module)
    _FakeClient.registered_paths = []
    yield
    _FakeClient.registered_paths = []


@pytest.fixture
def cli():
    """Import and return the CLI command after the fake module is installed.

    Imported lazily inside the fixture so the autouse fake_catalog_module
    fixture has already populated sys.modules.
    """
    # Ensure a fresh import so the top-level `from CDMSDataCatalog import ...`
    # binds to our fake.
    sys.modules.pop("cdms_verify.cli", None)
    from cdms_verify.cli import verify_catalog_registration
    return verify_catalog_registration


# --------------------------------------------------------------------------- #
# Test data setup helper
# --------------------------------------------------------------------------- #

def _make_tree(base: Path) -> Path:
    """Create a CDMS-rooted data tree and return the directory to scan."""
    data = base / "CDMS" / "Raw" / "Run1"
    data.mkdir(parents=True)
    (data / "file1.dat").write_text("content one")
    (data / "file2.dat").write_text("content two")
    return base / "CDMS"


def _invoke(cli, runner, scan_dir, db_path, extra=None):
    args = [
        "--local-dir", str(scan_dir),
        "--site", "SLAC",
        "--db-path", str(db_path),
    ]
    if extra:
        args.extend(extra)
    return runner.invoke(cli, args)


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

def test_all_unregistered_exits_1(cli, tmp_path):
    """With no registered paths, all files are UNREGISTERED -> exit 1."""
    scan_dir = _make_tree(tmp_path)
    db = tmp_path / "verification.db"

    _FakeClient.registered_paths = []  # nothing registered

    runner = CliRunner()
    result = _invoke(cli, runner, scan_dir, db)

    assert result.exit_code == 1
    summary = get_summary(db)
    assert summary["total"] == 2
    assert summary["unregistered"] == 2
    assert summary["registered"] == 0


def test_all_verified_exits_0(cli, tmp_path):
    """When every file's catalog path is registered, exit 0."""
    scan_dir = _make_tree(tmp_path)
    db = tmp_path / "verification.db"

    _FakeClient.registered_paths = [
        "/CDMS/Raw/Run1/file1.dat",
        "/CDMS/Raw/Run1/file2.dat",
    ]

    runner = CliRunner()
    result = _invoke(cli, runner, scan_dir, db)

    assert result.exit_code == 0
    summary = get_summary(db)
    assert summary["registered"] == 2
    assert summary["unregistered"] == 0


def test_partial_registration_exits_1(cli, tmp_path):
    scan_dir = _make_tree(tmp_path)
    db = tmp_path / "verification.db"

    _FakeClient.registered_paths = ["/CDMS/Raw/Run1/file1.dat"]

    runner = CliRunner()
    result = _invoke(cli, runner, scan_dir, db)

    assert result.exit_code == 1
    summary = get_summary(db)
    assert summary["registered"] == 1
    assert summary["unregistered"] == 1


def test_known_files_are_skipped_on_second_run(cli, tmp_path):
    """Files recorded in run 1 are skipped in run 2 (not re-inserted)."""
    scan_dir = _make_tree(tmp_path)
    db = tmp_path / "verification.db"
    _FakeClient.registered_paths = [
        "/CDMS/Raw/Run1/file1.dat",
        "/CDMS/Raw/Run1/file2.dat",
    ]

    runner = CliRunner()

    # Run 1: both files inserted.
    result1 = _invoke(cli, runner, scan_dir, db)
    assert result1.exit_code == 0
    assert get_summary(db)["total"] == 2

    # Run 2: both files already known -> skipped, total unchanged.
    result2 = _invoke(cli, runner, scan_dir, db)
    assert result2.exit_code == 0
    assert get_summary(db)["total"] == 2  # no new rows


def test_new_file_added_between_runs_is_recorded(cli, tmp_path):
    scan_dir = _make_tree(tmp_path)
    db = tmp_path / "verification.db"
    _FakeClient.registered_paths = [
        "/CDMS/Raw/Run1/file1.dat",
        "/CDMS/Raw/Run1/file2.dat",
    ]

    runner = CliRunner()
    _invoke(cli, runner, scan_dir, db)
    assert get_summary(db)["total"] == 2

    # Add a third file, unregistered.
    (scan_dir / "Raw" / "Run1" / "file3.dat").write_text("new content")

    result = _invoke(cli, runner, scan_dir, db)
    assert result.exit_code == 1  # file3 is unregistered
    summary = get_summary(db)
    assert summary["total"] == 3
    assert summary["unregistered"] == 1


def test_checksum_is_stored(cli, tmp_path):
    scan_dir = _make_tree(tmp_path)
    db = tmp_path / "verification.db"
    _FakeClient.registered_paths = ["/CDMS/Raw/Run1/file1.dat",
                                    "/CDMS/Raw/Run1/file2.dat"]

    runner = CliRunner()
    _invoke(cli, runner, scan_dir, db)

    expected = hashlib.sha256(b"content one").hexdigest()
    with get_db(db) as conn:
        row = conn.execute(
            "SELECT checksum FROM verification_results "
            "WHERE file_path LIKE '%file1.dat'"
        ).fetchone()
    assert row["checksum"] == expected


def test_size_and_mtime_stored(cli, tmp_path):
    scan_dir = _make_tree(tmp_path)
    db = tmp_path / "verification.db"
    _FakeClient.registered_paths = ["/CDMS/Raw/Run1/file1.dat",
                                    "/CDMS/Raw/Run1/file2.dat"]

    runner = CliRunner()
    _invoke(cli, runner, scan_dir, db)

    with get_db(db) as conn:
        row = conn.execute(
            "SELECT size, mtime, site FROM verification_results "
            "WHERE file_path LIKE '%file1.dat'"
        ).fetchone()
    assert row["size"] == len("content one")
    assert isinstance(row["mtime"], float)
    assert row["site"] == "SLAC"


def test_no_files_found_exits_0(cli, tmp_path):
    """An empty (but CDMS-rooted) directory exits 0 with nothing to do."""
    empty = tmp_path / "CDMS" / "Empty"
    empty.mkdir(parents=True)
    db = tmp_path / "verification.db"

    runner = CliRunner()
    result = _invoke(cli, runner, (tmp_path / "CDMS"), db)

    assert result.exit_code == 0
    assert get_summary(db)["total"] == 0


def test_nonrecursive_skips_subdirectories(cli, tmp_path):
    """--no-recursive only scans the top level of the given directory."""
    root = tmp_path / "CDMS"
    root.mkdir()
    (root / "top.dat").write_text("top")
    sub = root / "Sub"
    sub.mkdir()
    (sub / "nested.dat").write_text("nested")

    db = tmp_path / "verification.db"
    _FakeClient.registered_paths = ["/CDMS/top.dat"]

    runner = CliRunner()
    result = _invoke(cli, runner, root, db, extra=["--no-recursive"])

    # Only top.dat scanned; it's registered -> exit 0, total 1.
    assert result.exit_code == 0
    assert get_summary(db)["total"] == 1


def test_verbose_flag_runs(cli, tmp_path):
    """The --verbose flag should not change outcome, only output."""
    scan_dir = _make_tree(tmp_path)
    db = tmp_path / "verification.db"
    _FakeClient.registered_paths = ["/CDMS/Raw/Run1/file1.dat",
                                    "/CDMS/Raw/Run1/file2.dat"]

    runner = CliRunner()
    result = _invoke(cli, runner, scan_dir, db, extra=["--verbose"])
    assert result.exit_code == 0
    assert "VERIFIED" in result.output or "Checking" in result.output


def test_missing_local_dir_is_usage_error(cli, tmp_path):
    """A non-existent --local-dir is rejected by Click's path validation."""
    db = tmp_path / "verification.db"
    runner = CliRunner()
    result = runner.invoke(cli, [
        "--local-dir", str(tmp_path / "does-not-exist"),
        "--db-path", str(db),
    ])
    # Click exits 2 for usage/validation errors.
    assert result.exit_code == 2
