"""``hmp project new`` - thin wrapper around :func:`hydromodpy.create_project`."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_NOT_FOUND
from hydromodpy.core.state.paths import PROJECT_TOML_FILENAME

NAME: str = "new"
HELP: str = "Create a new project inside the workspace"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("project", help="Project name (under projects/)")
    parser.add_argument("--workspace", default=None, help="Workspace root (default: ~/hydromodpy/)")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.project import create_project

    try:
        project_dir = create_project(args.project, workspace=args.workspace)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    print(f"Project created: {project_dir}")
    print()
    print("Files:")
    print(f"  {project_dir / PROJECT_TOML_FILENAME}   <- shared settings")
    print(f"  {project_dir / 'run_demo.toml'}   <- executable run")
    print()
    print("Next steps:")
    print(f"  1. Edit {PROJECT_TOML_FILENAME} with your geographic/domain/flow settings")
    print(f"  2. Run: hmp run {project_dir / 'run_demo.toml'}")
