"""``hmp data add`` - thin wrapper around :func:`hydromodpy.add_data_entry`."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND

NAME: str = "add"
HELP: str = "Power-user command to ingest a single file with explicit metadata"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("file", help="Path to the source file to ingest")
    parser.add_argument("--type", dest="variable", default=None, help="Variable name")
    parser.add_argument("--provider", default="custom", help="Provider label")
    parser.add_argument("--crs", default=None, help="EPSG code (e.g. EPSG:2154)")
    parser.add_argument("--unit", default=None, help="Override unit")
    parser.add_argument("--station-id", default=None, dest="station_id")
    parser.add_argument("--workspace", default=None)
    parser.add_argument(
        "--frozen", action="store_true", help="Refuse to ingest if lockfile has no matching entry"
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    import hydromodpy as hmp

    if not args.variable:
        print("--type is required (e.g. --type piezometry)", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    try:
        result = hmp.add_data_entry(
            args.file,
            variable=args.variable,
            provider=args.provider,
            crs=args.crs,
            unit=args.unit,
            station_id=args.station_id,
            workspace=args.workspace,
            frozen=args.frozen,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    label = result["station_id"] or "(no station)"
    print(f"  Added: {result['variable']}/{result['provider']}/{label} -> {result['dest']}")
