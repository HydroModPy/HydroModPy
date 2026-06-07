"""``hmp project delete`` - thin wrapper around :func:`hydromodpy.delete_project`."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli._conventions import confirm_parser, workspace_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, EXIT_SIGINT

NAME: str = "delete"
HELP: str = "Delete a project and its catalog data"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), confirm_parser()],
        epilog="Example:\n  hmp project delete demo -y",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("project", help="Project name (directory under projects/)")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.project import delete_project

    if not args.yes:
        if not sys.stdin.isatty():
            print("Refusing to delete without -y in non-interactive mode.", file=sys.stderr)
            sys.exit(EXIT_SIGINT)
        try:
            resp = input(f"Delete project {args.project!r}? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            sys.exit(EXIT_SIGINT)
        if resp not in {"y", "yes"}:
            print("Aborted.", file=sys.stderr)
            sys.exit(EXIT_SIGINT)

    try:
        result = delete_project(args.project, workspace=args.workspace, force=args.yes)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    print(f"Deleted project {args.project} ({result['bytes_freed'] / 1e6:.2f} MB freed)")
