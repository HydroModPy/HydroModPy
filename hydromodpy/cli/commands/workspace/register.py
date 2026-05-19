"""``hmp workspace register`` - thin wrapper around :func:`hydromodpy.register_workspace`."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND, EXIT_OK

NAME: str = "register"
HELP: str = "Register a workspace catalog.duckdb in the global index"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("workspace_uri", help="Workspace path or URI (file://, s3://, ...)")
    parser.add_argument("--label", default=None, help="Optional human-readable label")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    import hydromodpy as hmp

    try:
        workspace_id = hmp.register_workspace(args.workspace_uri, label=args.label)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except Exception as exc:
        print(f"Cannot resolve workspace {args.workspace_uri!r}: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    print(workspace_id)
    sys.exit(EXIT_OK)
