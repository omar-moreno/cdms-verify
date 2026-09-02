#!/usr/bin/env python3
"""Command-line interface for the local file cleanup tool.

Deletes local files that are confirmed VERIFIED and checksum-matched in the
CDMS verification database. Intended to run as a cron job on a machine other
than the one that produced the database.
"""

from __future__ import annotations

import logging
import sys
from collections import Counter
from pathlib import Path

import click

from cdms_verify.cleanup import Decision, cleanup_directory
from cdms_verify.paths import extract_catalog_path


@click.command()
@click.option(
    "--local-dir",
    "-d",
    required=True,
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help="Local directory to clean up (must contain a 'CDMS' path component).",
)
@click.option(
    "--db-path",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the verification database (opened read-only).",
)
@click.option(
    "--recursive/--no-recursive",
    "-r/-nr",
    default=True,
    help="Recurse into subdirectories (default: True).",
)
@click.option(
    "--delete",
    is_flag=True,
    default=False,
    help="Actually delete eligible files. WITHOUT this flag, runs as a "
    "dry-run and deletes nothing.",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Enable verbose (DEBUG) logging.",
)
def cleanup(
    local_dir: str,
    db_path: str,
    recursive: bool,
    delete: bool,
    verbose: bool,
) -> None:
    """Delete local files verified and checksum-matched in the catalog.

    A file is deleted only when its catalog record is ``VERIFIED`` **and** its
    freshly-computed local checksum matches the stored checksum. Any other
    outcome keeps the file.

    By default this runs as a **dry-run** and deletes nothing; pass ``--delete``
    to perform actual deletions.

    Parameters
    ----------
    local_dir : str
        Local directory to clean up.
    db_path : str
        Path to the verification database.
    recursive : bool
        Whether to descend into subdirectories.
    delete : bool
        Perform deletions (otherwise dry-run).
    verbose : bool
        Enable DEBUG logging.

    Raises
    ------
    SystemExit
        Exits ``0`` on success (including dry-runs), or ``1`` if any file could
        not be evaluated or deleted (a ``KEEP_LOCAL_ERROR`` occurred).
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    local_path = Path(local_dir)
    if extract_catalog_path(local_path) is None:
        click.echo(
            click.style(
                f"✗ '{local_dir}' has no 'CDMS' path component; cannot derive "
                f"catalog paths.",
                fg="red",
            )
        )
        sys.exit(1)

    mode = (
        click.style("DELETE", fg="red", bold=True)
        if delete
        else click.style("DRY-RUN", fg="yellow", bold=True)
    )
    click.echo(f"Cleanup mode: {mode}")
    click.echo(f"  Local Directory : {local_dir}")
    click.echo(f"  Database        : {db_path}")
    click.echo("-" * 60)

    evaluations = cleanup_directory(local_path, db_path, recursive, delete)

    counts = Counter(e.decision for e in evaluations)

    # Per-file output for anything that was NOT a clean delete/keep-in-db,
    # so operators see exactly why files were retained.
    for e in evaluations:
        if e.decision is Decision.DELETE:
            verb = "DELETED" if delete else "WOULD DELETE"
            click.echo(click.style(f"{verb}: {e.local_path}", fg="green"))
        elif e.decision in (Decision.KEEP_CHECKSUM_MISMATCH, Decision.KEEP_LOCAL_ERROR):
            click.echo(
                click.style(
                    f"KEEP ({e.decision.value}): {e.local_path} — {e.detail}",
                    fg="red",
                )
            )

    # Summary.
    click.echo("\n" + "=" * 60)
    click.echo(click.style("CLEANUP SUMMARY", fg="cyan", bold=True))
    click.echo("=" * 60)
    total = len(evaluations)
    deleted = counts[Decision.DELETE]
    click.echo(f"Files evaluated:          {total}")
    click.echo(
        f"{'Deleted' if delete else 'Eligible (dry-run)'}: "
        f"{click.style(str(deleted), fg='green')}"
    )
    click.echo(f"Kept - not in DB:         {counts[Decision.KEEP_NOT_IN_DB]}")
    click.echo(f"Kept - not verified:      {counts[Decision.KEEP_NOT_VERIFIED]}")
    click.echo(
        f"Kept - checksum mismatch: "
        f"{click.style(str(counts[Decision.KEEP_CHECKSUM_MISMATCH]), fg='red')}"
    )
    click.echo(
        f"Kept - local error:       "
        f"{click.style(str(counts[Decision.KEEP_LOCAL_ERROR]), fg='red')}"
    )

    if not delete and deleted > 0:
        click.echo(
            "\n"
            + click.style(
                f"ℹ  Dry-run: {deleted} file(s) would be deleted. "
                f"Re-run with --delete to remove them.",
                fg="yellow",
            )
        )

    # Exit non-zero if anything went wrong (mismatches or errors need review).
    problems = (
        counts[Decision.KEEP_CHECKSUM_MISMATCH] + counts[Decision.KEEP_LOCAL_ERROR]
    )
    sys.exit(1 if problems > 0 else 0)


if __name__ == "__main__":
    cleanup()
