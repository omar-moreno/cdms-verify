"""CDMS Data Catalog query helpers.

This module wraps interactions with the :class:`CDMSDataCatalog` client,
providing a resilient function for retrieving datasets under a given catalog
path. Errors raised by the underlying client are logged and converted into an
empty result set so that a transient catalog failure degrades gracefully.

Functions
---------
get_datasets
    Recursively retrieve datasets registered under a catalog path.
"""

from __future__ import annotations

import logging
from typing import Any, List

# Optional third-party dependencies of the underlying catalog client. They
# are imported defensively so that this module can be imported (and its
# non-network code tested) even when the client stack is unavailable.
try:  # pragma: no cover - import guard
    import datacat  # type: ignore
except ImportError:  # pragma: no cover
    datacat = None  # type: ignore

try:  # pragma: no cover - import guard
    import requests  # type: ignore
except ImportError:  # pragma: no cover
    requests = None  # type: ignore

logger = logging.getLogger(__name__)


def get_datasets(
    dc: "CDMSDataCatalog",  # noqa: F821 - forward ref to external type
    path: str = "/CDMS",
    site: str = "All",
) -> List[Any]:
    """Retrieve datasets registered under a catalog path.

    Performs two searches against the catalog and merges the results:

    1. A search at ``path`` itself, returning datasets directly contained
       there.
    2. A recursive search at ``path + "**"``, returning datasets in all
       nested containers.

    Parameters
    ----------
    dc : CDMSDataCatalog
        An initialized data catalog client exposing ``dc.client.search``.
    path : str, optional
        The catalog path to search under. Defaults to the catalog root
        ``/CDMS``.
    site : str, optional
        The storage site to filter datasets by (e.g. ``SLAC``). Defaults to
        ``All``.

    Returns
    -------
    list
        A list of dataset objects returned by the catalog client. Each object
        is expected to expose a ``.path`` attribute. Returns an empty list if
        the query fails.

    Notes
    -----
    Exceptions from the catalog client (``datacat.error.DcClientException``)
    and HTTP errors (``requests.exceptions.HTTPError``) are caught, logged,
    and result in an empty list rather than propagating. This keeps a single
    failed lookup from aborting the whole verification run.

    Examples
    --------
    >>> datasets = get_datasets(catalog, "/CDMS/Raw", site="SLAC")  # doctest: +SKIP
    >>> paths = [d.path for d in datasets]  # doctest: +SKIP
    """
    try:
        datasets = dc.client.search(path, site=site)
        # The "**" suffix triggers a recursive search into child containers.
        datasets.extend(dc.client.search(path + "**", site=site))
    except Exception as err:  # noqa: BLE001 - see notes on specific types
        # We catch broadly because the specific exception classes live in
        # optional dependencies that may not be importable in all envs.
        if datacat is not None and isinstance(
            err, datacat.error.DcClientException
        ):
            logger.error("DcClientException %s: %s", err, path)
        elif requests is not None and isinstance(
            err, requests.exceptions.HTTPError
        ):
            logger.error("HTTPError %s: %s", err, path)
        else:
            logger.error("Unexpected error querying %s: %s", path, err)
        return []

    return datasets
