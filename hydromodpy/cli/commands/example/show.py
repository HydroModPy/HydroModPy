"""``hmp example show`` - one example, file by file, cached or missing."""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import format_parser, workspace_parser
from hydromodpy.cli.output import emit

NAME: str = "show"
HELP: str = "Show one example file by file, each marked cached or missing"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(reads_none=True), format_parser()],
        epilog="Example:\n  hmp example show example_id",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("example_id", help="Example id, as listed by 'hmp example list'")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.project.examples.rows import human_size, show_rows

    payload = show_rows(args.example_id)

    def table() -> None:
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

    emit(
        args,
        "example show",
        payload,
        table=table,
        csv=(
            ("role", "dest", "size", "cached", "sha256"),
            [*payload["files"], *payload["data"]],
        ),
    )
