"""CDMS Data Catalog verification toolkit.

This package provides utilities to reconcile a local file tree against the
CDMS Data Catalog. It scans local files, derives their expected catalog
paths, checks registration status, computes checksums, and persists results
to a SQLite database and/or human-readable reports.

Modules
-------
paths
    Path normalization and catalog-path extraction helpers.

Examples
--------
Run the CLI after installation::

    $ cdms-verify --local-dir /data/CDMS/Raw --site SLAC
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
