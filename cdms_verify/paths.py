"""Path manipulation helpers for the CDMS Data Catalog.

The CDMS Data Catalog enforces a strict path convention in which every
catalog path is rooted at ``/CDMS``. This module centralizes the logic for
normalizing arbitrary user input into that convention and for translating a
local filesystem path into its corresponding catalog path.

Functions
---------
normalize_path
    Coerce an arbitrary string into a valid ``/CDMS``-rooted catalog path.
extract_catalog_path
    Derive a catalog path from a local filesystem path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def normalize_path(path: str) -> str:
    """Normalize a path to a valid CDMS catalog path.

    Enforces the catalog's strict path requirements:

    1. Empty or whitespace-only paths are converted to the root ``/CDMS``.
    2. Relative paths are made absolute.
    3. The ``/CDMS`` prefix is enforced.
    4. Trailing and duplicate slashes are collapsed/stripped.

    Parameters
    ----------
    path : str
        The input path string. May be absolute (e.g. ``/CDMS/Raw``) or
        relative (e.g. ``Raw/Run1``). Leading and trailing whitespace is
        ignored. ``None`` is tolerated and treated as an empty string.

    Returns
    -------
    str
        The normalized path. Guaranteed to start with ``/CDMS`` and to not
        end with a slash (unless the path is exactly ``/CDMS``).

    Examples
    --------
    >>> normalize_path("")
    '/CDMS'
    >>> normalize_path("/")
    '/CDMS'
    >>> normalize_path("/CDMS/Raw/Run1/")
    '/CDMS/Raw/Run1'
    >>> normalize_path("/CUTE/Raw")
    '/CDMS/CUTE/Raw'
    >>> normalize_path("  /CDMS/Data/  ")
    '/CDMS/Data'
    >>> normalize_path("//Raw//Run1//")
    '/CDMS/Raw/Run1'
    """
    # Strip whitespace and tolerate None.
    path = (path or "").strip()

    # Collapse duplicate internal slashes so "//Raw//Run1" behaves.
    parts = [p for p in path.split("/") if p]

    # Empty input -> catalog root.
    if not parts:
        return "/CDMS"

    # Enforce the /CDMS prefix without duplicating it.
    if parts[0] != "CDMS":
        parts.insert(0, "CDMS")

    return "/" + "/".join(parts)


def extract_catalog_path(local_path: Path) -> Optional[str]:
    """Derive a catalog path from a local filesystem path.

    Locates the ``CDMS`` component within the path and reconstructs the
    portion from that component onward as a normalized catalog path.

    Parameters
    ----------
    local_path : pathlib.Path
        A local filesystem path that is expected to contain a ``CDMS``
        component somewhere in its parts, e.g.
        ``/home/user/CDMS/Raw/run1.dat``.

    Returns
    -------
    str or None
        The normalized catalog path (e.g. ``/CDMS/Raw/run1.dat``) if a
        ``CDMS`` component is found, otherwise ``None``.

    Notes
    -----
    Only the first occurrence of ``CDMS`` is used as the split point. If the
    path contains multiple ``CDMS`` components, the earliest one wins.

    Examples
    --------
    >>> from pathlib import Path
    >>> extract_catalog_path(Path("/home/user/CDMS/Raw/run1.dat"))
    '/CDMS/Raw/run1.dat'
    >>> extract_catalog_path(Path("/tmp/nothing/here.txt")) is None
    True
    """
    parts = local_path.parts

    try:
        index = parts.index("CDMS")
    except ValueError:
        return None

    extracted = "/".join(parts[index:])
    return normalize_path(extracted)
