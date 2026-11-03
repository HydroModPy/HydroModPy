"""``hmp project list`` - the projects under ``projects/`` of a workspace."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.conventions import verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, apply_verbosity, resolve_workspace

NAME: str = "list"
HELP: str = "List projects available in a workspace"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), verbosity_parser()],
        epilog="Example:\n  hmp project list -w ~/hydromodpy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.cli._workers.project import list_projects

    workspace = resolve_workspace(args.workspace)
    try:
        projects = list_projects(workspace)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    if not projects:
        print(f"# no projects in {workspace}")
        return

    print(f"# workspace projects ({len(projects)}): {workspace}")
    for project in projects:
        details = []
        if project["has_project_toml"]:
            details.append("project.toml")
        if project["run_tomls"]:
            details.append(f"{len(project['run_tomls'])} run TOML(s)")
        suffix = f"  [{', '.join(details)}]" if details else ""
        print(f"  {project['name']}{suffix}")
