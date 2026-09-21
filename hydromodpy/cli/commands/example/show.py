"""``hmp example show`` - one example, file by file, cached or missing."""

from __future__ import annotations

import argparse
import json
import sys

from hydromodpy.cli._conventions import format_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND

NAME: str = "show"
HELP: str = "Show one example file by file, each marked cached or missing"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP, parents=[format_parser()])
    parser.add_argument("example_id", help="Example id, as listed by 'hmp example list'")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.example import human_size, show_rows

    try:
        payload = show_rows(args.example_id)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return
    if args.format == "csv":
        print("role,dest,size,cached,sha256")
        for row in [*payload["files"], *payload["data"]]:
            print(f"{row['role']},{row['dest']},{row['size']},{row['cached']},{row['sha256']}")
        return

    print(f"{payload['id']}  {payload['title']}")
    print(f"  {payload['summary']}")
    print(f"  runtime: {payload['runtime']}")
    print(
        f"  payload: {human_size(payload['total_size'])} "
        f"in {payload['file_count']} file(s), "
        f"{human_size(payload['missing_size'])} still to download"
    )
    for label, key in (("Project files", "files"), ("Data files", "data")):
        print()
        print(f"{label}:")
        for row in payload[key]:
            state = "cached " if row["cached"] else "missing"
            print(f"  [{state}] {human_size(row['size']):>9}  {row['dest']}")
