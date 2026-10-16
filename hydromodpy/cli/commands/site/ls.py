"""``hmp site ls``: list the sites declared in the workspace."""

from __future__ import annotations

import argparse
import csv
import json
import sys

from hydromodpy.cli._conventions import format_parser, workspace_parser
from hydromodpy.cli.helpers import exit_code_for

NAME: str = "ls"
HELP: str = "List the sites declared in data/sites/catalog.csv"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser()],
        epilog="Example:\n  hmp site ls --tag bretagne --format csv",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--tag", default=None, help="Only the sites carrying this tag")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli.commands.site._workspace import workspace_root
    from hydromodpy.core.site import SITE_ROW_COLUMNS
    from hydromodpy.data.sites.catalog import read_catalog

    root = workspace_root(args.workspace)
    try:
        rows = read_catalog(root)
    except Exception as exc:  # noqa: BLE001 - map errors to typed exit codes
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))
    if args.tag is not None:
        rows = [row for row in rows if args.tag in row.tags]
    records = [row.to_mapping() for row in rows]
    if args.format == "json":
        print(json.dumps(records, indent=2))
        return
    if args.format == "csv":
        writer = csv.DictWriter(sys.stdout, fieldnames=list(SITE_ROW_COLUMNS))
        writer.writeheader()
        for record in records:
            writer.writerow({key: "" if value is None else value for key, value in record.items()})
        return
    if not records:
        print("no site declared")
        return
    columns = ("site", "label", "gauge", "uri", "x_outlet", "y_outlet", "crs", "tags")
    table = [[_cell(record[column]) for column in columns] for record in records]
    widths = [
        max(len(column), *(len(line[i]) for line in table)) for i, column in enumerate(columns)
    ]
    for line in [list(columns), *table]:
        print(
            "  ".join(cell.ljust(width) for cell, width in zip(line, widths, strict=True)).rstrip()
        )


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)
