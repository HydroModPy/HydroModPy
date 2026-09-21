"""``hmp example list`` - the shipped catalogue, read offline from the wheel."""

from __future__ import annotations

import argparse
import json
import sys

from hydromodpy.cli._conventions import format_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND

NAME: str = "list"
HELP: str = "List the examples this build ships, and what is missing from the cache"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP, parents=[format_parser()])
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.example import human_size, list_rows

    try:
        rows = list_rows()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    if args.format == "json":
        print(json.dumps(rows, indent=2))
        return
    if args.format == "csv":
        print("id,title,runtime,total_size,missing_size")
        for row in rows:
            print(
                f"{row['id']},{row['title']},{row['runtime']},{row['total_size']},{row['missing_size']}"
            )
        return

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
