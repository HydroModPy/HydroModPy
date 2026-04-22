"""``hmp lock`` — manage the reproducible data lockfile."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy._cli.helpers import (
    EXIT_CONFIG,
    EXIT_DATA_ERROR,
    EXIT_NOT_FOUND,
    resolve_workspace,
)


NAME = "lock"
HELP = "Manage the reproducible data lockfile (hydromodpy.lock)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = parser.add_subparsers(dest="lock_command")

    update = sub.add_parser(
        "update",
        help="Scan the cache and write/update hydromodpy.lock",
    )
    update.add_argument("--workspace", default=None)
    update.add_argument(
        "--output", default=None, help="Destination lockfile (default: <workspace>/hydromodpy.lock)"
    )

    archive = sub.add_parser(
        "archive",
        help="Create a portable archive (lockfile + artefacts)",
    )
    archive.add_argument("output", help="Destination archive (.tar / .tar.gz / .tar.zst)")
    archive.add_argument("--workspace", default=None)

    restore = sub.add_parser("restore", help="Restore an archive and verify SHA-256")
    restore.add_argument("input", help="Archive to restore")
    restore.add_argument("--workspace", default=None)
    restore.add_argument("--output", default=None, help="Target directory")

    verify = sub.add_parser("verify", help="Verify the cache matches the lockfile")
    verify.add_argument("--workspace", default=None)
    verify.add_argument("--lockfile", default=None, help="Explicit lockfile path")

    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    sub = getattr(args, "lock_command", None)
    if sub == "update":
        _cmd_update(args)
    elif sub == "archive":
        _cmd_archive(args)
    elif sub == "restore":
        _cmd_restore(args)
    elif sub == "verify":
        _cmd_verify(args)
    else:
        print("Usage: hmp lock {update|archive|restore|verify} [options]", file=sys.stderr)
        sys.exit(EXIT_CONFIG)


def _cmd_update(args: argparse.Namespace) -> None:
    from hydromodpy.data.lockfile import LOCKFILE_NAME, write_lockfile
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    workspace = resolve_workspace(args.workspace)
    db_path = workspace / "data" / "cache.duckdb"
    dest = Path(args.output).expanduser().resolve() if args.output else (workspace / LOCKFILE_NAME)
    with DataCatalogDuckDB(db_path) as catalog:
        written = write_lockfile(catalog, dest)
    print(f"  Lockfile written: {written}")


def _cmd_archive(args: argparse.Namespace) -> None:
    from hydromodpy.data.lockfile import archive_lockfile
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    workspace = resolve_workspace(args.workspace)
    db_path = workspace / "data" / "cache.duckdb"
    dest = Path(args.output).expanduser().resolve()
    with DataCatalogDuckDB(db_path) as catalog:
        archive_lockfile(catalog, dest)
    print(f"  Archive written: {dest}")


def _cmd_restore(args: argparse.Namespace) -> None:
    from hydromodpy.data.lockfile import restore_archive

    workspace = resolve_workspace(args.workspace)
    src = Path(args.input).expanduser().resolve()
    dest_dir = (
        Path(args.output).expanduser().resolve()
        if args.output
        else (workspace / "data" / "restored")
    )
    restore_archive(src, dest_dir)
    print(f"  Restored {src} -> {dest_dir}")


def _cmd_verify(args: argparse.Namespace) -> None:
    from hydromodpy.data.lockfile import LOCKFILE_NAME, verify_frozen
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    workspace = resolve_workspace(args.workspace)
    db_path = workspace / "data" / "cache.duckdb"
    lockfile = (
        Path(args.lockfile).expanduser().resolve() if args.lockfile else (workspace / LOCKFILE_NAME)
    )
    if not lockfile.is_file():
        print(f"  Lockfile not found: {lockfile}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    with DataCatalogDuckDB(db_path) as catalog:
        mismatches = verify_frozen(catalog, lockfile)
    if not mismatches:
        print("  OK: catalog matches lockfile")
        return
    print(f"  {len(mismatches)} mismatch(es):")
    for m in mismatches:
        print(f"    [{m.kind}] {m.variable}/{m.source}/{m.station_id}")
    sys.exit(EXIT_DATA_ERROR)
