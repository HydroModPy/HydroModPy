"""``hmp project delete`` - thin wrapper around :func:`hydromodpy.delete_project`."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_NOT_FOUND, EXIT_SIGINT

NAME: str = "delete"
HELP: str = "Delete a project and its catalog data"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("project", help="Project name (directory under projects/)")
    parser.add_argument("--workspace", default=None, help="Workspace root")
    parser.add_argument("--force", action="store_true", help="Skip the confirmation prompt")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.project import delete_project

    if not args.force:
        if not sys.stdin.isatty():
            print("Refusing to delete without --force in non-interactive mode.", file=sys.stderr)
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
        result = delete_project(args.project, workspace=args.workspace, force=args.force)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    print(f"Deleted project {args.project} ({result['bytes_freed'] / 1e6:.2f} MB freed)")
