"""``hmp project new`` - scaffold a project under ``projects/`` of a workspace."""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import format_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.output import emit
from hydromodpy.cli.refs import resolve_workspace
from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME

NAME: str = "new"
HELP: str = "Create a new project inside the workspace"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog="Example:\n  hmp project new my_project -w ~/hydromodpy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("project", help="Project name (under projects/)")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.data.workspace.folders import create_project

    workspace = resolve_workspace(args.workspace)
    project_dir = create_project(args.project, workspace=workspace)

    def table() -> None:
        print(f"Project created: {project_dir}")
        print()
        print("Files:")
        print(f"  {project_dir / PROJECT_MARKER_FILENAME}   <- shared settings")
        print(f"  {project_dir / 'run_demo.toml'}   <- executable run")
        print()
        print("Next steps:")
        print(f"  1. Edit {PROJECT_MARKER_FILENAME} with your geographic/domain/flow settings")
        print(f"  2. Run: hmp run {project_dir / 'run_demo.toml'}")

    emit(args, "project new", {"path": project_dir}, table=table)
