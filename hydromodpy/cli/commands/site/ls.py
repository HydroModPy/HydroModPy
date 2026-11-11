"""``hmp site ls``: list the sites declared in the workspace."""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import format_parser, workspace_parser
from hydromodpy.cli.output import emit, print_table

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
    from hydromodpy.cli.refs import resolve_workspace
    from hydromodpy.data.sites.catalog import read_catalog

    root = resolve_workspace(args.workspace)
    rows = read_catalog(root)
    if args.tag is not None:
        rows = [row for row in rows if args.tag in row.tags]
    records = [row.to_mapping() for row in rows]

    def table() -> None:
        if records:
            print_table("site ls", records)
        else:
            print("no site declared")

    emit(args, "site ls", records, table=table)
