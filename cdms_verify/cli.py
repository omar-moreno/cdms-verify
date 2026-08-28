"""Command-line interface for CDMS catalog verification.

Defines the ``cdms-verify`` entry point which orchestrates scanning,
catalog querying, database persistence, and report generation. This module
wires together the pure-logic helpers from the sibling modules and handles
all user-facing I/O.

Functions
---------
verify_catalog_registration
    The Click command implementing the verification workflow.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import click

from cdms_verify.catalog import get_datasets
from cdms_verify.database import (
        get_known_file_paths,
        init_db, 
        save_results,
)
from cdms_verify.paths import extract_catalog_path, normalize_path
from cdms_verify.scanning import ( 
    CHECKSUM_ERROR, 
    calculate_sha256, 
    scan_local_files,
    stat_file,
)

# Imported lazily-friendly: the concrete client used at runtime.
from CDMSDataCatalog import CDMSDataCatalog


@click.command()
@click.option(
    "--local-dir", "-d", required=True,
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help="Local directory containing the files to verify.",
)
@click.option(
    "--site", "-s", default="SLAC", type=str,
    help="Target site to verify against (default: SLAC).",
)
@click.option(
    "--recursive/--no-recursive", "-r/-nr", default=True,
    help="Scan subdirectories recursively (default: True).",
)
@click.option(
    "--db-path", default="verification.db",
    type=click.Path(dir_okay=False),
    help="SQLite database file for storing results (default: verification.db).",
)
@click.option(
    "--verbose", "-v", is_flag=True, default=False,
    help="Enable verbose output for debugging.",
)
def verify_catalog_registration(
    local_dir: str,
    site: str,
    recursive: bool,
    db_path: str,
    verbose: bool,
) -> None:
    """Verify local files against the CDMS Data Catalog.

    Scans ``local_dir``, derives each file's expected catalog path, checks it
    against datasets registered at ``site``, computes a SHA256 checksum (only
    when one is not already stored from a prior run) and persists results to a
    SQLite database.

    Parameters
    ----------
    local_dir : str
        Local directory to verify. Must exist and be a directory.
    site : str
        Target catalog site (e.g. ``SLAC``).
    recursive : bool
        Whether to descend into subdirectories.
    db_path : str
        Path to the SQLite database file for persisting results.
    verbose : bool
        If ``True``, print per-file progress information.

    Raises
    ------
    SystemExit
        Exits with status ``1`` on initialization failure, scanning errors, or
        if any discrepancies (unregistered files or errors) are found. Exits
        with status ``0`` when everything is verified or no files are found.

    Notes
    -----
    Files that already appear in the database (matched by ``file_path``) are
    skipped entirely: they are not re-checksummed, not registration-checked,
    and not written again. Only newly discovered files are processed and
    recorded. Every invocation writes a ``verification_runs`` row so there is
    an audit trail of each run, even when no new files were found. The size
    and mtime of new files are persisted so an external tool can perform its
    own change detection independently.

    """
    # Ensure the database schema exists before we read from or write to it.
    init_db(db_path)

    # Initialize the catalog client.
    try:
        catalog = CDMSDataCatalog()
        if verbose:
            click.echo(click.style("\u2713 CDMSDataCatalog initialized.", fg="green"))
    except Exception as exc:  # noqa: BLE001
        click.echo(click.style(f"\u2717 Error initializing catalog: {exc}", fg="red"))
        sys.exit(1)

    local_path_obj = Path(local_dir)
    catalog_path = extract_catalog_path(local_path_obj) or "/CDMS"

    click.echo(click.style("Starting verification...", fg="cyan"))
    click.echo(f"  Local Directory : {local_dir}")
    click.echo(f"  Catalog Prefix  : {catalog_path}")
    click.echo(f"  Target Site     : {site}")
    click.echo(f"  Database        : {db_path}")
    click.echo("-" * 60)

    # Collect files.
    try:
        local_files = list(scan_local_files(local_path_obj, recursive))
    except (FileNotFoundError, NotADirectoryError) as exc:
        click.echo(click.style(f"\u2717 {exc}", fg="red"))
        sys.exit(1)

    if not local_files:
        click.echo(click.style("No files found in the specified directory.", fg="yellow"))
        sys.exit(0)

    click.echo(f"Found {len(local_files)} local files. Checking registration...\n")

    datasets = get_datasets(catalog, catalog_path, site=site)
    dataset_paths = [d.path for d in datasets]
    click.echo(f"Found {len(dataset_paths)} datasets registered in the catalog.")

    # Fetch the set of files already recorded in the database. Any file that
    # already exists is skipped entirely on this run.
    known_paths = get_known_file_paths(db_path, local_files)
    if verbose:
        click.echo(
            f"{len(known_paths)} of {len(local_files)} files already known."
        )

    results: List[Dict[str, Any]] = []

    registered = 0
    unregistered = 0
    errors = 0

    for local_file in local_files:
        # Skip any file that already exists in the database.
        if local_file in known_paths:
            if verbose:
                click.echo(click.style(f"  \u23ed  SKIP (already in DB): {local_file}", fg="blue"))
            continue

        expected = normalize_path(extract_catalog_path(Path(local_file)))
        if verbose:
            click.echo(f"Checking: {local_file} -> {expected}")

        fstat = stat_file(local_file)
        checksum = calculate_sha256(local_file)

        result_row: Dict[str, Any] = {
            "file_path": local_file,
            "catalog_path": expected,
            "status": "",
            "checksum": "",
            "size": fstat.size,
            "mtime": fstat.mtime,
        }

        if checksum == CHECKSUM_ERROR:
            result_row["status"] = "ERROR"
            errors += 1
            click.echo(click.style(f"ERROR (checksum): {local_file}", fg="red"))
        elif expected in dataset_paths:
            result_row["status"] = "VERIFIED"
            registered += 1
            dataset_paths.remove(expected)
            if verbose:
                click.echo(click.style(f"\u2705 VERIFIED: {local_file}", fg="green"))
        else:
            result_row["status"] = "UNREGISTERED"
            unregistered += 1
            click.echo(click.style(f"UNREGISTERED: {local_file}", fg="yellow"))

        results.append(result_row)
   
    # Persist new files (idempotent per file_path). site is stored per row.
    inserted = save_results(db_path, results, site)
    click.echo(f"\nInserted {inserted} new file(s) into: {db_path}")
    
    # Console summary (counts are for THIS run's newly processed files).
    click.echo("\n" + "=" * 60)
    click.echo(click.style("VERIFICATION SUMMARY (new files this run)", fg="cyan", bold=True))
    click.echo("=" * 60)
    click.echo(f"New Files Processed:  {len(results)}")
    click.echo(f"Correctly Registered: {click.style(str(registered), fg='green')}")
    click.echo(f"Unregistered:         {click.style(str(unregistered), fg='red')}")
    click.echo(f"Errors:               {click.style(str(errors), fg='red')}")

    if unregistered > 0 or errors > 0:
        click.echo("\n" + click.style(
            "\u26a0\ufe0f  Discrepancies found among new files.",
            fg="yellow", bold=True,
        ))
        sys.exit(1)

    click.echo("\n" + click.style(
        "\u2705 All new local files are correctly registered.", fg="green", bold=True,
    ))
    sys.exit(0)

if __name__ == "__main__":
    verify_catalog_registration()
