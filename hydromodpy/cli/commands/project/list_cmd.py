"""``hmp project list`` - thin wrapper around :func:`hydromodpy.list_projects`."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_NOT_FOUND

NAME: str = "list"
HELP: str = "List projects available in a workspace"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace root (default: walk up from cwd, fallback ~/hydromodpy/)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    import hydromodpy as hmp

    try:
        projects = hmp.list_projects(args.workspace)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    if not projects:
        print("# no projects")
        return

    print(f"# workspace projects ({len(projects)}):")
    for project in projects:
        details = []
        if project["has_project_toml"]:
            details.append("hydromodpy.toml")
        if project["run_tomls"]:
            details.append(f"{len(project['run_tomls'])} run(s)")
        suffix = f"  [{', '.join(details)}]" if details else ""
        print(f"  {project['name']}{suffix}")
