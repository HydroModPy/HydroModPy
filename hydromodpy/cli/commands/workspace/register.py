"""``hmp workspace register`` - add project roots to the machine-wide global index."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND, EXIT_OK

NAME: str = "register"
HELP: str = "Register a project in the global index (a workspace registers its projects)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "root_uri",
        help=(
            "Project root, or workspace root to expand into the projects it holds "
            "(path or file:// URI). The directory must exist."
        ),
    )
    parser.add_argument("--label", default=None, help="Optional human-readable label")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.workspace import register_projects

    try:
        outcome = register_projects(args.root_uri, label=args.label)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except Exception as exc:
        print(f"Cannot resolve {args.root_uri!r}: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    known = outcome["known"]
    if outcome["registered"]:
        for project_id in outcome["registered"]:
            print(project_id)
    elif known:
        print(f"Nothing to do: the {len(known)} project(s) under {args.root_uri} are registered.")
    else:
        print(f"No project under {args.root_uri} yet, so nothing was registered.")
    sys.exit(EXIT_OK)
