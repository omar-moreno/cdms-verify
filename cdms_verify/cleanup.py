"""Local file cleanup based on catalog verification.

Provides the decision logic for safely deleting local files that have been
verified and checksum-matched in the CDMS Data Catalog database. This module
runs on a machine *other* than the one that produced the database; files are
matched by their machine-independent catalog path, not their absolute local
path.

A file is eligible for deletion only when **both** conditions hold:

1. Its catalog record has ``status == 'VERIFIED'``.
2. The local file's freshly-computed SHA256 matches the stored checksum.

Any uncertainty (missing record, status mismatch, checksum mismatch, unreadable
file) results in the file being **kept**.

Functions
---------
evaluate_file
    Decide whether a single local file may be deleted.
cleanup_directory
    Evaluate (and optionally delete) all files under a local directory.

Classes
-------
Decision
    Enumeration of possible per-file deletion outcomes.
Evaluation
    The result of evaluating one file.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from cdms_verify.database import (
    connect_readonly,
    get_verification_by_catalog_path,
)
from cdms_verify.paths import extract_catalog_path, normalize_path
from cdms_verify.scanning import (
    CHECKSUM_ERROR,
    calculate_sha256,
    scan_local_files,
)

logger = logging.getLogger(__name__)


class Decision(str, Enum):
    """The outcome of evaluating a single file for deletion.

    Attributes
    ----------
    DELETE
        File is verified and checksum-matched; eligible for deletion.
    KEEP_NOT_IN_DB
        No record for this catalog path exists in the database.
    KEEP_NOT_VERIFIED
        A record exists but its status is not ``VERIFIED``.
    KEEP_CHECKSUM_MISMATCH
        The local checksum does not match the stored checksum.
    KEEP_LOCAL_ERROR
        The local file could not be read/hashed, its catalog path could not be
        derived, or its deletion failed.
    """

    DELETE = "DELETE"
    KEEP_NOT_IN_DB = "KEEP_NOT_IN_DB"
    KEEP_NOT_VERIFIED = "KEEP_NOT_VERIFIED"
    KEEP_CHECKSUM_MISMATCH = "KEEP_CHECKSUM_MISMATCH"
    KEEP_LOCAL_ERROR = "KEEP_LOCAL_ERROR"


@dataclass
class Evaluation:
    """The result of evaluating one file.

    Attributes
    ----------
    local_path : str
        The absolute local path of the file evaluated.
    catalog_path : str or None
        The derived catalog path, or ``None`` if it could not be derived.
    decision : Decision
        The deletion decision.
    detail : str
        A human-readable explanation of the decision.
    """

    local_path: str
    catalog_path: str | None
    decision: Decision
    detail: str


def evaluate_file(local_path: str, conn: sqlite3.Connection) -> Evaluation:
    """Decide whether a single local file may be safely deleted.

    Parameters
    ----------
    local_path : str
        Absolute path to the local file to evaluate.
    conn : sqlite3.Connection
        An open read-only connection to the verification database, e.g. from
        :func:`cdms_verify.database.connect_readonly`. Passing an existing
        connection avoids reopening the database for every file.

    Returns
    -------
    Evaluation
        The decision and its rationale. Only :attr:`Decision.DELETE` marks a
        file as eligible for deletion.

    Notes
    -----
    This function performs **no** deletion. It computes the local file's
    checksum and compares it against the stored, verified record. All failure
    and mismatch cases resolve to a ``KEEP_*`` decision so that the caller
    never deletes on uncertainty.
    """
    catalog_path = extract_catalog_path(Path(local_path))
    if catalog_path is None:
        return Evaluation(
            local_path,
            None,
            Decision.KEEP_LOCAL_ERROR,
            "could not derive catalog path (no 'CDMS' component)",
        )
    catalog_path = normalize_path(catalog_path)

    record = get_verification_by_catalog_path(conn, catalog_path)
    if record is None:
        return Evaluation(
            local_path,
            catalog_path,
            Decision.KEEP_NOT_IN_DB,
            "no record in database",
        )

    if record["status"] != "VERIFIED":
        return Evaluation(
            local_path,
            catalog_path,
            Decision.KEEP_NOT_VERIFIED,
            f"status is {record['status']!r}, not VERIFIED",
        )

    local_checksum = calculate_sha256(local_path)
    if local_checksum == CHECKSUM_ERROR:
        return Evaluation(
            local_path,
            catalog_path,
            Decision.KEEP_LOCAL_ERROR,
            "failed to compute local checksum",
        )

    if local_checksum != record["checksum"]:
        return Evaluation(
            local_path,
            catalog_path,
            Decision.KEEP_CHECKSUM_MISMATCH,
            "local checksum does not match stored checksum",
        )

    return Evaluation(
        local_path,
        catalog_path,
        Decision.DELETE,
        "verified and checksum matches",
    )


def cleanup_directory(
    directory: Path,
    db_path: str,
    recursive: bool,
    delete: bool,
) -> list[Evaluation]:
    """Evaluate all files under a directory and optionally delete eligible ones.

    Opens a single read-only database connection and reuses it for every file,
    avoiding the overhead of reopening the database per lookup.

    Parameters
    ----------
    directory : pathlib.Path
        The local directory to clean up. Must contain a ``CDMS`` component in
        its path so catalog paths can be derived.
    db_path : str
        Path to the verification database (opened read-only).
    recursive : bool
        Whether to descend into subdirectories.
    delete : bool
        If ``True``, files with a :attr:`Decision.DELETE` decision are removed.
        If ``False``, nothing is deleted — the function only reports what
        *would* happen.

    Returns
    -------
    list of Evaluation
        One :class:`Evaluation` per file scanned.

    Raises
    ------
    FileNotFoundError
        If ``directory`` does not exist.
    NotADirectoryError
        If ``directory`` is not a directory.

    Notes
    -----
    Deletion, when enabled, is best-effort per file: a failure to delete one
    file is logged and does not abort processing of the rest. The evaluation
    for a file whose deletion fails is downgraded to
    :attr:`Decision.KEEP_LOCAL_ERROR`.
    """
    evaluations: list[Evaluation] = []

    # One read-only connection for the entire scan.
    with connect_readonly(db_path) as conn:
        for local_file in scan_local_files(directory, recursive):
            result = evaluate_file(local_file, conn)

            if result.decision is Decision.DELETE and delete:
                try:
                    os.remove(local_file)
                    logger.info("DELETED %s (%s)", local_file, result.detail)
                except OSError as exc:
                    logger.error("FAILED to delete %s: %s", local_file, exc)
                    result = Evaluation(
                        result.local_path,
                        result.catalog_path,
                        Decision.KEEP_LOCAL_ERROR,
                        f"deletion failed: {exc}",
                    )
            else:
                logger.debug(
                    "%s %s (%s)", result.decision.value, local_file, result.detail
                )

            evaluations.append(result)

    return evaluations
