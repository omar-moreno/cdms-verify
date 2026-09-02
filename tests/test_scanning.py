"""Tests for cdms_verify.scanning.

Covers checksum calculation, file stat-ing, and directory scanning against a
real (temporary) filesystem provided by pytest's ``tmp_path`` fixture.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from cdms_verify.scanning import (
    CHECKSUM_ERROR,
    FileStat,
    calculate_sha256,
    scan_local_files,
    stat_file,
)

# --------------------------------------------------------------------------- #
# calculate_sha256
# --------------------------------------------------------------------------- #


def test_calculate_sha256_known_value(tmp_path):
    """The digest of b'hello' matches the well-known SHA256 value."""
    f = tmp_path / "hello.txt"
    f.write_bytes(b"hello")
    expected = hashlib.sha256(b"hello").hexdigest()
    assert calculate_sha256(f) == expected


def test_calculate_sha256_empty_file(tmp_path):
    f = tmp_path / "empty.dat"
    f.write_bytes(b"")
    assert calculate_sha256(f) == hashlib.sha256(b"").hexdigest()


def test_calculate_sha256_large_multichunk(tmp_path):
    """A file larger than the read chunk hashes correctly across chunks."""
    # 3 MiB of repeating data exercises the chunked read loop (1 MiB chunks).
    data = b"x" * (3 * 1024 * 1024 + 17)
    f = tmp_path / "big.bin"
    f.write_bytes(data)
    assert calculate_sha256(f) == hashlib.sha256(data).hexdigest()


def test_calculate_sha256_accepts_str_path(tmp_path):
    f = tmp_path / "s.txt"
    f.write_bytes(b"abc")
    assert calculate_sha256(str(f)) == hashlib.sha256(b"abc").hexdigest()


def test_calculate_sha256_missing_file_returns_sentinel(tmp_path):
    missing = tmp_path / "does-not-exist.dat"
    assert calculate_sha256(missing) == CHECKSUM_ERROR


def test_calculate_sha256_directory_returns_sentinel(tmp_path):
    """Attempting to hash a directory fails gracefully with the sentinel."""
    assert calculate_sha256(tmp_path) == CHECKSUM_ERROR


# --------------------------------------------------------------------------- #
# stat_file
# --------------------------------------------------------------------------- #


def test_stat_file_returns_size_and_mtime(tmp_path):
    f = tmp_path / "a.dat"
    f.write_bytes(b"12345")
    st = stat_file(f)
    assert isinstance(st, FileStat)
    assert st.size == 5
    assert isinstance(st.mtime, float)


def test_stat_file_missing_returns_none_fields(tmp_path):
    st = stat_file(tmp_path / "nope.dat")
    assert st == FileStat(size=None, mtime=None)


def test_stat_file_accepts_str_path(tmp_path):
    f = tmp_path / "b.dat"
    f.write_bytes(b"ab")
    assert stat_file(str(f)).size == 2


# --------------------------------------------------------------------------- #
# scan_local_files
# --------------------------------------------------------------------------- #


def test_scan_local_files_nonrecursive_top_level_only(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.txt").write_text("c")  # should NOT be yielded

    found = {Path(p).name for p in scan_local_files(tmp_path, recursive=False)}
    assert found == {"a.txt", "b.txt"}


def test_scan_local_files_recursive_includes_subdirs(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    sub = tmp_path / "sub" / "deeper"
    sub.mkdir(parents=True)
    (sub / "c.txt").write_text("c")

    found = {Path(p).name for p in scan_local_files(tmp_path, recursive=True)}
    assert found == {"a.txt", "c.txt"}


def test_scan_local_files_yields_absolute_paths(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    paths = list(scan_local_files(tmp_path, recursive=False))
    assert len(paths) == 1
    assert Path(paths[0]).is_absolute()


def test_scan_local_files_skips_directories(tmp_path):
    (tmp_path / "only_a_dir").mkdir()
    (tmp_path / "file.txt").write_text("f")
    found = {Path(p).name for p in scan_local_files(tmp_path, recursive=True)}
    assert found == {"file.txt"}


def test_scan_local_files_empty_dir_yields_nothing(tmp_path):
    assert list(scan_local_files(tmp_path, recursive=True)) == []


def test_scan_local_files_missing_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        list(scan_local_files(tmp_path / "nope", recursive=False))


def test_scan_local_files_on_file_raises_notadirectory(tmp_path):
    f = tmp_path / "a_file.txt"
    f.write_text("x")
    with pytest.raises(NotADirectoryError):
        list(scan_local_files(f, recursive=False))


def test_scan_local_files_is_generator(tmp_path):
    """scan_local_files should be lazy (a generator), not return a list."""
    import types

    (tmp_path / "a.txt").write_text("a")
    result = scan_local_files(tmp_path, recursive=False)
    assert isinstance(result, types.GeneratorType)
