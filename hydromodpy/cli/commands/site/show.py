"""``hmp site show``: print one site declared in the workspace."""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import format_parser, workspace_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, refuse
from hydromodpy.cli.output import emit

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
    rows = read_catalog(root)
    match = next((row for row in rows if row.site == args.name), None)
    if match is None:
        names = ", ".join(row.site for row in rows) or "none"
        refuse(f"No site {args.name!r} in {catalog_path(root)}. Declared: {names}.", EXIT_NOT_FOUND)
    record = match.to_mapping()

    def table() -> None:
        for key, value in record.items():
            print(f"{key:9} {'' if value is None else value}")

    emit(args, "site show", record, table=table)
