"""``hmp process list`` - the capabilities this build serves."""

from __future__ import annotations

import argparse
import csv
import json
import sys

from hydromodpy.cli._conventions import format_parser

NAME: str = "list"
HELP: str = "List the capabilities this build can be invoked as"

_COLUMNS = ("id", "version", "title")


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[format_parser()],
        epilog="Example:\n  hmp process list --format json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.process import list_capabilities

    records = list_capabilities()
    if args.format == "json":
        print(json.dumps(records, indent=2, ensure_ascii=False))
        return
    if args.format == "csv":
        writer = csv.DictWriter(sys.stdout, fieldnames=_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
        return
    if not records:
        print("(this build serves no capability)")
        return
    for record in records:
        print(f"{record['id']}  {record['version']}  {record['title']}")
