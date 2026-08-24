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
        get_existing_file_info,
        init_db, 
        save_results_to_db
)
from cdms_verify.paths import extract_catalog_path, normalize_path
from cdms_verify.reports import generate_html_report_from_db
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
    "--output-dir", "-o", default=".",
    type=click.Path(file_okay=False, dir_okay=True),
    help="Directory to save the HTML report (default: current dir).",
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
    output_dir: str,
    db_path: str,
    verbose: bool,
) -> None:
    """Verify local files against the CDMS Data Catalog.

    Scans ``local_dir``, derives each file's expected catalog path, checks it
    against datasets registered at ``site``, computes a SHA256 checksum (only
    when one is not already stored from a prior run), persists results to a
    SQLite database, and renders an HTML report from that database.

    Parameters
    ----------
    local_dir : str
        Local directory to verify. Must exist and be a directory.
    site : str
        Target catalog site (e.g. ``SLAC``).
    recursive : bool
        Whether to descend into subdirectories.
    output_dir : str
        Directory in which the HTML report is written; created if needed.
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
    Change detection is treated as a distinct failure condition. On each run
    the file's current size and mtime are compared against the values stored
    in the most recent prior run:

    - **Unchanged** (size *and* mtime match): the stored checksum is reused
      and the file proceeds to the registration check.
    - **Changed** (size *or* mtime differs, or the file can no longer be
      stat-ed): the file is flagged with status ``FILE_CHANGED`` and its
      checksum is **not** recomputed. Per the retained-record policy, the old
      checksum, size, and mtime are stored together so the change re-flags on
      every subsequent run until the file is re-verified.
    - **New** (no prior record): the checksum is computed for the first time.

    Any of unregistered files, checksum errors, or changed files causes the
    command to exit with status ``1``. Size and mtime are persisted for new
    and unchanged files; changed files retain the last-known size/mtime.

    """
    output_path_obj = Path(output_dir)
    output_path_obj.mkdir(parents=True, exist_ok=True)

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
    click.echo(f"  Output Dir      : {output_dir}")
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

    # Batch-fetch prior records (checksum + size + mtime) so we can skip
    # recomputation for files that are unchanged. One query instead of N.
    cached_info = get_existing_file_info(db_path, local_files)
    if verbose:
        click.echo(f"Found {len(cached_info)} cached record(s) from prior runs.\n")

    stats: Dict[str, int] = {
        "total": 0, "registered": 0, "unregistered": 0, 
        "errors": 0, "changed": 0,
    }
    results: List[Dict[str, Any]] = []

    reused = 0
    computed = 0
    changed = 0

    for local_file in local_files:
        stats["total"] += 1
        expected = normalize_path(extract_catalog_path(Path(local_file)))

        if verbose:
            click.echo(f"Checking: {local_file} -> {expected}")

        # Stat the file now so we can (a) detect changes vs. the cached record
        # and (b) persist current size/mtime for external change-detection.
        fstat = stat_file(local_file)

        prior = cached_info.get(local_file)

        result_row: Dict[str, Any] = {
            "file_path": local_file,
            "catalog_path": expected,
            "status": "",
            "checksum": "",
            "size": fstat.size,
            "mtime": fstat.mtime,
        }

        if prior is not None:
            # A prior record exists: determine whether the file has changed.
            can_compare = fstat.size is not None and fstat.mtime is not None
            unchanged = (
                can_compare
                and prior["size"] == fstat.size
                and prior["mtime"] == fstat.mtime
            )

            if unchanged:
                # File is byte-for-byte identical (per size/mtime): reuse.
                result_row["checksum"] = prior["checksum"]
                reused += 1
                if verbose:
                    click.echo(click.style(
                        "  \u21ba reused stored checksum (unchanged)", fg="blue"
                    ))
            else:
                # File changed (or is now un-stat-able): flag as FILE_CHANGED.
                # We deliberately do NOT recompute the checksum here.
                result_row["status"] = "FILE_CHANGED"
                result_row["checksum"] = prior["checksum"]  # keep last-known value
                result_row["size"] = prior["size"]
                result_row["mtime"] = prior["mtime"]
                stats["changed"] += 1
                changed += 1
                click.echo(click.style(
                    f"FILE_CHANGED: {local_file}",
                    fg="yellow",
                ))
                results.append(result_row)
                continue  # skip the registration check for changed files
        else:
            # No prior record: compute the checksum for the first time.
            result_row["checksum"] = calculate_sha256(local_file)
            computed += 1
            
        # Registration check (only reached for unchanged or brand-new files).
        checksum = result_row["checksum"]
        if checksum == CHECKSUM_ERROR:
            result_row["status"] = "ERROR"
            stats["errors"] += 1
            click.echo(click.style(f"ERROR (checksum): {local_file}", fg="red"))
        elif expected in dataset_paths:
            result_row["status"] = "VERIFIED"
            stats["registered"] += 1
            dataset_paths.remove(expected)
            if verbose:
                click.echo(click.style(f"\u2705 VERIFIED: {local_file}", fg="green"))
        else:
            result_row["status"] = "UNREGISTERED"
            stats["unregistered"] += 1
            click.echo(click.style(f"UNREGISTERED: {local_file}", fg="yellow"))

        results.append(result_row)
   
    click.echo(
        f"\nChecksums: {computed} computed, {reused} reused, "
        f"{changed} flagged as changed."
    )
    click.echo(f"Datasets in catalog with no local match: {len(dataset_paths)}")

    # Persist to database.
    run_id = save_results_to_db(
        db_path, results, stats, local_dir, catalog_path or "/CDMS", site,
    )
    click.echo(f"Results saved to database (run #{run_id}): {db_path}")
    
    # Generate the HTML report by reading the run back from the database.
    html_filename = output_path_obj / "verification_report.html"
    click.echo("\nGenerating report from database...")
    generate_html_report_from_db(db_path, run_id, str(html_filename))
    click.echo(f"HTML report saved to: {html_filename}")

    # Summary.
    click.echo("\n" + "=" * 60)
    click.echo(click.style("VERIFICATION SUMMARY", fg="cyan", bold=True))
    click.echo("=" * 60)
    click.echo(f"Total Files Scanned:  {stats['total']}")
    click.echo(f"Correctly Registered: {click.style(str(stats['registered']), fg='green')}")
    click.echo(f"Unregistered:         {click.style(str(stats['unregistered']), fg='red')}")
    click.echo(f"Changed:              {click.style(str(stats['changed']), fg='yellow')}")
    click.echo(f"Errors:               {click.style(str(stats['errors']), fg='red')}")

    discrepancies = (
        stats["unregistered"] > 0
        or stats["errors"] > 0
        or stats["changed"] > 0
    )
    if discrepancies:
        click.echo("\n" + click.style(
            "\u26a0\ufe0f  Discrepancies found. Review or re-registration needed.",
            fg="yellow", bold=True,
        ))
        sys.exit(1)

    click.echo("\n" + click.style(
        "\u2705 All local files are correctly registered and unchanged.",
        fg="green", bold=True,
    ))
    sys.exit(0)


if __name__ == "__main__":
    verify_catalog_registration()
