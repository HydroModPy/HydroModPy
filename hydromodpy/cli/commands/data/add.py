"""``hmp data add`` - ingest a single file with explicit metadata."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND, resolve_workspace

NAME: str = "add"
HELP: str = "Power-user command to ingest a single file with explicit metadata"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("file", help="Path to the source file to ingest")
    parser.add_argument(
        "--type", dest="variable", default=None, help="Variable name (e.g. piezometry)"
    )
    parser.add_argument("--provider", default="custom", help="Provider label (default: custom)")
    parser.add_argument("--crs", default=None, help="EPSG code (e.g. EPSG:2154)")
    parser.add_argument("--unit", default=None, help="Override unit")
    parser.add_argument("--station-id", default=None, help="Station id for single-station files")
    parser.add_argument("--workspace", default=None)
    parser.add_argument(
        "--frozen",
        action="store_true",
        help="Refuse to ingest if the lockfile has no matching entry",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.data.adapters import (
        convert_asc_to_geotiff,
        convert_timeseries_csv_to_parquet,
        convert_vector_to_geoparquet,
    )
    from hydromodpy.data.data_freeze import LOCKFILE_NAME, read_lockfile, sha256_of
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
