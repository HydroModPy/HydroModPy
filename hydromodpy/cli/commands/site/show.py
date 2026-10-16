"""``hmp site show``: print one site declared in the workspace."""

from __future__ import annotations

import argparse
import csv
import json
import sys

from hydromodpy.cli._conventions import format_parser, workspace_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, exit_code_for

NAME: str = "show"
HELP: str = "Print one site of data/sites/catalog.csv"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser()],
        epilog="Example:\n  hmp site show couesnon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("name", help="Site name")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli.helpers import resolve_workspace
    from hydromodpy.data.sites.catalog import catalog_path, read_catalog

    root = resolve_workspace(args.workspace)
    try:
        rows = read_catalog(root)
    except Exception as exc:  # noqa: BLE001 - map errors to typed exit codes
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))
    match = next((row for row in rows if row.site == args.name), None)
    if match is None:
        names = ", ".join(row.site for row in rows) or "none"
        print(
            f"No site {args.name!r} in {catalog_path(root)}. Declared: {names}.",
            file=sys.stderr,
        )
        sys.exit(EXIT_NOT_FOUND)
    record = match.to_mapping()
    if args.format == "json":
        print(json.dumps(record, indent=2))
        return
    if args.format == "csv":
        writer = csv.writer(sys.stdout, lineterminator="\n")
        writer.writerow(record)
        writer.writerow("" if value is None else value for value in record.values())
        return
    for key, value in record.items():
        print(f"{key:9} {'' if value is None else value}")
