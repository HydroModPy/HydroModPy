"""``hmp example list`` - the shipped catalogue, read offline from the wheel."""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import format_parser, workspace_parser
from hydromodpy.cli.output import emit

NAME: str = "list"
HELP: str = "List the examples this build ships, and what is missing from the cache"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(reads_none=True), format_parser()],
        epilog="Examples:\n  hmp example list\n  hmp example list --format json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.example import human_size, list_rows

    rows = list_rows()

    def table() -> None:
        if not rows:
            print("  (this build ships no example)")
            return
        print(f"{'ID':<4} {'TITLE':<40} {'PAYLOAD':>9} {'MISSING':>9}  RUNTIME")
        for row in rows:
            print(
                f"{row['id']:<4} {row['title'][:40]:<40} "
                f"{human_size(row['total_size']):>9} {human_size(row['missing_size']):>9}  "
                f"{row['runtime']}"
            )
        print()
        print("  hmp example show <id>   file by file")
        print("  hmp example add <id>    fetch what is missing and write it into a workspace")

    emit(args, "example list", rows, table=table)
