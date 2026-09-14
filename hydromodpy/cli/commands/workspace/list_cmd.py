"""``hmp workspace list`` - projects registered in the machine-wide global index."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_OK

NAME: str = "list"
HELP: str = "List the projects registered in the machine-wide global index"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.workspace import list_registered_projects

    df = list_registered_projects()
    if df is None or df.empty:
        print("(no registered projects)")
        sys.exit(EXIT_OK)

    if args.json:
        print(df.to_json(orient="records", date_format="iso", indent=2))
        sys.exit(EXIT_OK)

    columns = [
        c
        for c in ("project_id", "label", "project_uri", "created_at", "last_scanned_at")
        if c in df.columns
    ]
    if not columns:
        columns = list(df.columns)
    print(df[columns].to_string(index=False))
    sys.exit(EXIT_OK)
