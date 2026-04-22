"""``hmp data`` — inspect and manage custom data artefacts."""

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


NAME = "data"
HELP = "Inspect and manage custom data artefacts in the workspace"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = parser.add_subparsers(dest="data_command")

    check = sub.add_parser(
        "check",
        help="Validate the drag-and-drop <variable>_custom/ folders without ingesting",
    )
    check.add_argument("--workspace", default=None, help="Workspace root")
    check.add_argument(
        "--variable", default=None, help="Restrict to one variable (e.g. piezometry)"
    )
    check.add_argument(
        "--fix",
        action="store_true",
        help="Attempt to repair stale catalog entries",
    )

    listp = sub.add_parser("list", help="List artefacts indexed in the workspace cache")
    listp.add_argument("--workspace", default=None)
    listp.add_argument("--variable", default=None, help="Filter by variable")
    listp.add_argument("--provider", default=None, help="Filter by provider")

    add = sub.add_parser(
        "add",
        help="Power-user command to ingest a single file with explicit metadata",
    )
    add.add_argument("file", help="Path to the source file to ingest")
    add.add_argument(
        "--type", dest="variable", default=None, help="Variable name (e.g. piezometry)"
    )
    add.add_argument("--provider", default="custom", help="Provider label (default: custom)")
    add.add_argument("--crs", default=None, help="EPSG code (e.g. EPSG:2154)")
    add.add_argument("--unit", default=None, help="Override unit")
    add.add_argument("--station-id", default=None, help="Station id for single-station files")
    add.add_argument("--workspace", default=None)
    add.add_argument(
        "--frozen",
        action="store_true",
        help="Refuse to ingest if the lockfile has no matching entry",
    )

    remove = sub.add_parser("remove", help="Remove cache entries for a variable/provider/station")
    remove.add_argument("--workspace", default=None)
    remove.add_argument("--variable", default=None)
    remove.add_argument("--provider", default=None)
    remove.add_argument("--station-id", default=None, dest="station_id")
    remove.add_argument(
        "--delete-files",
        action="store_true",
        help="Also delete the underlying files on disk",
    )

    prune = sub.add_parser("prune", help="Drop cache entries older than N days")
    prune.add_argument("--workspace", default=None)
    prune.add_argument(
        "--older-than", type=int, default=30, help="Age threshold in days (default: 30)"
    )
    prune.add_argument("--delete-files", action="store_true")

    export = sub.add_parser("export", help="Archive the cache (data + lockfile) to a portable file")
    export.add_argument("output", help="Destination archive (.tar / .tar.gz / .tar.zst)")
    export.add_argument("--workspace", default=None)

    import_p = sub.add_parser("import", help="Restore a cache archive into the workspace")
    import_p.add_argument("input", help="Archive produced by 'hmp data export'")
    import_p.add_argument("--workspace", default=None)

    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    sub = getattr(args, "data_command", None)
    if sub == "check":
        _cmd_check(args)
    elif sub == "list":
        _cmd_list(args)
    elif sub == "add":
        _cmd_add(args)
    elif sub == "remove":
        _cmd_remove(args)
    elif sub == "prune":
        _cmd_prune(args)
    elif sub == "export":
        _cmd_export(args)
    elif sub == "import":
        _cmd_import(args)
    else:
        print(
            "Usage: hmp data {check|list|add|remove|prune|export|import} [options]",
            file=sys.stderr,
        )
        sys.exit(EXIT_CONFIG)


def _cmd_check(args: argparse.Namespace) -> None:
    from hydromodpy.data.auto_scan import check_custom
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    workspace = resolve_workspace(args.workspace)
    issues = check_custom(workspace, variable=args.variable)

    if getattr(args, "fix", False):
        db_path = workspace / "data" / "cache.duckdb"
        if db_path.exists():
            with DataCatalogDuckDB(db_path) as catalog:
                summary = catalog.check_and_fix()
            print(
                f"  catalog: dropped {summary['dropped']} stale entries, "
                f"refreshed {summary['refreshed']} mtimes."
            )
        else:
            print(f"  (no cache at {db_path}; skipped catalog fix)")

    if not issues:
        print(f"  OK: no schema issues in {workspace}")
        return
    print(f"  {len(issues)} issue(s) found:")
    for path, msg in issues:
        print(f"    {path}: {msg}")
    sys.exit(EXIT_DATA_ERROR)


def _cmd_list(args: argparse.Namespace) -> None:
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    workspace = resolve_workspace(args.workspace)
    db_path = workspace / "data" / "cache.duckdb"
    if not db_path.exists():
        print(f"  (no cache found at {db_path})")
        return

    with DataCatalogDuckDB(db_path) as catalog:
        df = catalog.list_entries(
            variable=args.variable,
            source=args.provider,
        )
        if df.empty:
            print("  (empty cache — drop files in <variable>_custom/ then run 'hmp run')")
            return
        cols = [c for c in ("variable", "source", "station_id", "file_path") if c in df.columns]
        print(df[cols].to_string(index=False))


def _cmd_add(args: argparse.Namespace) -> None:
    from hydromodpy.data.adapters import (
        convert_asc_to_geotiff,
        convert_timeseries_csv_to_parquet,
        convert_vector_to_geoparquet,
    )
    from hydromodpy.data.lockfile import LOCKFILE_NAME, read_lockfile, sha256_of
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
    from hydromodpy.data.scaffold import VARIABLES

    workspace = resolve_workspace(args.workspace)
    src = Path(args.file).expanduser().resolve()
    if not src.is_file():
        print(f"File not found: {src}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    if getattr(args, "frozen", False):
        lockfile = workspace / LOCKFILE_NAME
        if not lockfile.is_file():
            print(f"--frozen requested but no {lockfile}", file=sys.stderr)
            sys.exit(EXIT_CONFIG)
        expected = {la.sha256 for la in read_lockfile(lockfile)}
        if sha256_of(src) not in expected:
            print(
                f"--frozen: {src} SHA-256 does not match any entry in {lockfile}",
                file=sys.stderr,
            )
            sys.exit(EXIT_CONFIG)

    if not args.variable:
        print("--type is required (e.g. --type piezometry)", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    spec = next((s for s in VARIABLES if s.name == args.variable), None)
    if spec is None:
        names = ", ".join(s.name for s in VARIABLES)
        print(f"Unknown variable {args.variable!r}. Available: {names}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    blobs = workspace / "data" / "blobs" / spec.name / args.provider
    blobs.mkdir(parents=True, exist_ok=True)

    if spec.kind == "timeseries":
        station_id = args.station_id or src.stem
        dest = blobs / f"{station_id}.parquet"
        convert_timeseries_csv_to_parquet(src, dest)
    elif spec.kind == "raster":
        station_id = None
        dest = blobs / f"{src.stem}.tif"
        convert_asc_to_geotiff(src, dest)
    elif spec.kind == "vector":
        station_id = None
        dest = blobs / f"{src.stem}.parquet"
        convert_vector_to_geoparquet(src, dest)
    else:
        print(f"Unsupported kind {spec.kind!r}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    with DataCatalogDuckDB(workspace / "data" / "cache.duckdb") as catalog:
        catalog.register(
            variable=spec.name,
            source=args.provider,
            station_id=station_id,
            file_path=str(src),
            crs=args.crs,
            unit=args.unit or spec.unit,
            is_custom=True,
            fetch_metadata={
                "pivot_path": str(dest),
                "pivot_format": spec.pivot,
            },
        )
    print(f"  Added: {spec.name}/{args.provider}/{station_id or src.stem} -> {dest}")


def _cmd_remove(args: argparse.Namespace) -> None:
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    workspace = resolve_workspace(args.workspace)
    db_path = workspace / "data" / "cache.duckdb"
    if not db_path.exists():
        print(f"  (no cache at {db_path})")
        return
    with DataCatalogDuckDB(db_path) as catalog:
        n = catalog.invalidate(
            variable=args.variable,
            source=args.provider,
            station_id=args.station_id,
            delete_files=args.delete_files,
        )
    print(f"  Removed {n} entry(ies).")


def _cmd_prune(args: argparse.Namespace) -> None:
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    workspace = resolve_workspace(args.workspace)
    db_path = workspace / "data" / "cache.duckdb"
    if not db_path.exists():
        print(f"  (no cache at {db_path})")
        return
    with DataCatalogDuckDB(db_path) as catalog:
        n = catalog.prune_older_than(
            days=args.older_than,
            delete_files=args.delete_files,
        )
    print(f"  Pruned {n} entry(ies) older than {args.older_than} day(s).")


def _cmd_export(args: argparse.Namespace) -> None:
    from hydromodpy.data.lockfile import archive_lockfile
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    workspace = resolve_workspace(args.workspace)
    db_path = workspace / "data" / "cache.duckdb"
    dest = Path(args.output).expanduser().resolve()
    with DataCatalogDuckDB(db_path) as catalog:
        archive_lockfile(catalog, dest)
    print(f"  Exported cache to {dest}")


def _cmd_import(args: argparse.Namespace) -> None:
    from hydromodpy.data.lockfile import restore_archive

    workspace = resolve_workspace(args.workspace)
    src = Path(args.input).expanduser().resolve()
    dest = workspace / "data" / "imported"
    restore_archive(src, dest)
    print(f"  Imported {src} into {dest}")
