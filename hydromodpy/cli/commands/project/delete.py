"""``hmp project delete`` - remove a project directory and everything it holds.

A project with an attempt still beating is refused: its worker writes into
it. A run that was published is named on stderr before the removal, since
its copies now point at a source that is gone.
"""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.conventions import confirm_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import (
    EXIT_NOT_FOUND,
    EXIT_SIGINT,
    EXIT_USAGE,
    EXIT_WRITE_CONFLICT,
    apply_verbosity,
    resolve_workspace,
)

NAME: str = "delete"
HELP: str = "Delete a project directory: its configs, runs, sessions and trash"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), confirm_parser(), verbosity_parser()],
        epilog="Example:\n  hmp project delete demo -w ~/hydromodpy -y",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("project", help="Project name (directory under projects/)")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.cli._workers.project import delete_project
    from hydromodpy.core.state.paths import PROJECTS_DIRNAME
    from hydromodpy.results.catalog.indexer import scan_tree
    from hydromodpy.results.outcome import effective_status
    from hydromodpy.results.storage.contract import RUN_PUBLISHED_FILENAME

    workspace = resolve_workspace(args.workspace)
    project_dir = workspace / PROJECTS_DIRNAME / args.project
    if not project_dir.is_dir():
        print(f"No such project: {project_dir}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    entries = scan_tree(project_dir).values()
    running = [
        e.rel_dir for e in entries if e.kind != "session" and effective_status(e.path) == "running"
    ]
    if running:
        print(
            f"{args.project} has {len(running)} attempt(s) still running "
            f"({', '.join(running)}). Stop them first.",
            file=sys.stderr,
        )
        sys.exit(EXIT_WRITE_CONFLICT)

    if not args.yes:
        if not sys.stdin.isatty():
            print("Refusing to delete without -y in non-interactive mode.", file=sys.stderr)
            sys.exit(EXIT_USAGE)
        try:
            resp = input(f"Delete project {project_dir}? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            sys.exit(EXIT_SIGINT)
        if resp not in {"y", "yes"}:
            print("Aborted.", file=sys.stderr)
            sys.exit(EXIT_SIGINT)

    for entry in entries:
        if (entry.path / RUN_PUBLISHED_FILENAME).is_file():
            print(
                f"{entry.rel_dir} was published: its copies now point at a deleted source",
                file=sys.stderr,
            )
    result = delete_project(args.project, workspace=workspace, force=args.yes)
    print(f"Deleted project {args.project} ({result['bytes_freed'] / 1e6:.2f} MB freed)")
