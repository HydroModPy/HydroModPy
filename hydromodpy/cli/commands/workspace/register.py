"""``hmp workspace register`` - register a workspace in the global index."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND, EXIT_OK
from hydromodpy.core.state.paths import CATALOG_FILENAME

NAME: str = "register"
HELP: str = "Register a workspace catalog.duckdb in the global index"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "workspace_uri",
        help="Workspace path or URI (file://, s3://, ...). Must contain catalog.duckdb.",
    )
    parser.add_argument("--label", default=None, help="Optional human-readable label")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.core.state.global_index import GlobalIndex
    from hydromodpy.core.state.paths import resolve_workspace

    uri = args.workspace_uri
    try:
        local = resolve_workspace(uri)
    except Exception as exc:
        print(f"Cannot resolve workspace {uri!r}: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    catalog = Path(local) / CATALOG_FILENAME
    if not catalog.is_file():
        print(
            f"Workspace {uri!r} has no {CATALOG_FILENAME} at {catalog}. "
            "Run 'hmp workspace init' or 'hmp run' first.",
            file=sys.stderr,
        )
        sys.exit(EXIT_NOT_FOUND)

    with GlobalIndex() as gi:
        workspace_id = gi.register_workspace(uri, label=args.label)
    print(workspace_id)
    sys.exit(EXIT_OK)
