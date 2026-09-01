"""Local filesystem scanning and checksum utilities.

This module provides the building blocks for discovering files on the local
filesystem and computing their SHA256 checksums. Both operations are
streaming/chunked where possible to keep memory usage bounded regardless of
directory size or file size.

Functions
---------
calculate_sha256
    Compute the SHA256 hex digest of a file.
scan_local_files
    Yield the absolute paths of files within a directory.
stat_file
    Return the size and modification time of a file.
"""

from __future__ import annotations

import os
import hashlib
from pathlib import Path
from typing import Generator, Union, NamedTuple, Optional

# Read files in 1 MiB chunks to bound memory usage for large files.
_CHUNK_SIZE = 1024 * 1024

#: Sentinel returned by :func:`calculate_sha256` when hashing fails.
CHECKSUM_ERROR = "ERROR_CALCULATING"

class FileStat(NamedTuple):
    """Lightweight container for a file's size and modification time.

    Attributes
    ----------
    size : int or None
        File size in bytes, or ``None`` if the file could not be stat-ed.
    mtime : float or None
        Modification time as POSIX epoch seconds (may include a fractional
        part), or ``None`` if the file could not be stat-ed.
    """

    size: Optional[int]
    mtime: Optional[float]


def calculate_sha256(file_path: Union[str, Path]) -> str:
    """Compute the SHA256 checksum of a file.

    The file is read incrementally in fixed-size chunks so that arbitrarily
    large files can be hashed without loading them fully into memory.

    Parameters
    ----------
    file_path : str or pathlib.Path
        Path to the file to hash.

    Returns
    -------
    str
        The lowercase hexadecimal SHA256 digest of the file contents, or the
        sentinel :data:`CHECKSUM_ERROR` (``"ERROR_CALCULATING"``) if the file
        could not be read.

    Notes
    -----
    Any exception during reading (permissions, disappearing files, I/O
    errors) is swallowed and reported via the sentinel return value rather
    than propagated, so that a single unreadable file does not abort a whole
    verification run.

    Examples
    --------
    >>> import tempfile, os
    >>> path = tempfile.mktemp()
    >>> _ = open(path, "wb").write(b"hello")
    >>> calculate_sha256(path)
    '2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824'
    >>> os.remove(path)
    """
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as handle:
            for block in iter(lambda: handle.read(_CHUNK_SIZE), b""):
                sha256_hash.update(block)
        return sha256_hash.hexdigest()
    except Exception:
        return CHECKSUM_ERROR


def scan_local_files(
    directory_path: Path,
    recursive: bool,
) -> Generator[str, None, None]:
    """Yield absolute paths of all files within a directory.

    Parameters
    ----------
    directory_path : pathlib.Path
        The directory to scan. Must exist and be a directory.
    recursive : bool
        If ``True``, descend into all subdirectories using a recursive glob.
        If ``False``, only files directly within ``directory_path`` are
        yielded.

    Yields
    ------
    str
        The absolute path of each regular file found, as a string.

    Raises
    ------
    FileNotFoundError
        If ``directory_path`` does not exist.
    NotADirectoryError
        If ``directory_path`` exists but is not a directory.

    Notes
    -----
    Only regular files are yielded; directories, symlinks to directories, and
    other special entries are skipped. Ordering is filesystem-dependent and
    should not be relied upon.

    Examples
    --------
    >>> from pathlib import Path
    >>> files = list(scan_local_files(Path("/tmp"), recursive=False))  # doctest: +SKIP
    """
    if not directory_path.exists():
        raise FileNotFoundError(f"Directory not found: {directory_path}")

    if not directory_path.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {directory_path}")

    if recursive:
        for file_path in directory_path.rglob("*"):
            if file_path.is_file():
                yield str(file_path.absolute())
    else:
        for item in directory_path.iterdir():
            if item.is_file():
                yield str(item.absolute())

def stat_file(file_path: Union[str, Path]) -> FileStat:
    """Return the size and modification time of a file.

    Parameters
    ----------
    file_path : str or pathlib.Path
        Path to the file to stat.

    Returns
    -------
    FileStat
        A named tuple ``(size, mtime)``. Both fields are ``None`` if the file
        cannot be stat-ed (e.g. it was removed between scanning and stat-ing,
        or is unreadable).

    Notes
    -----
    ``mtime`` is taken from :attr:`os.stat_result.st_mtime` and therefore uses
    the platform's modification-time resolution. As with checksums, any error
    is swallowed and reported via ``None`` fields rather than raised, so a
    single problematic file does not abort a verification run.

    Examples
    --------
    >>> import tempfile, os
    >>> path = tempfile.mktemp()
    >>> _ = open(path, "wb").write(b"hello")
    >>> st = stat_file(path)
    >>> st.size
    5
    >>> isinstance(st.mtime, float)
    True
    >>> os.remove(path)
    """
    try:
        info = os.stat(file_path)
        return FileStat(size=info.st_size, mtime=info.st_mtime)
    except OSError:
        return FileStat(size=None, mtime=None)
