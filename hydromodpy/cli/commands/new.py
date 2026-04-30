"""``hmp new`` - create a new project inside a workspace."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_NOT_FOUND

NAME: str = "new"
HELP: str = "Create a new project inside the workspace"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "project",
        help="Project name (will be created under projects/)",
    )
    parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace root (default: ~/hydromodpy/)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.data.scaffold import DEFAULT_ROOT, create_project

    workspace_root = Path(args.workspace or DEFAULT_ROOT).expanduser().resolve()
    catalog_ok = (workspace_root / "hydromodpy.duckdb").exists()
    layout_ok = (workspace_root / "data").is_dir() or (workspace_root / "projects").is_dir()
    if not (catalog_ok or layout_ok):
        print(
            f"'{workspace_root}' does not look like a HydroModPy workspace. "
            "Run 'hmp init <workspace>' first or use --workspace.",
            file=sys.stderr,
        )
        sys.exit(EXIT_NOT_FOUND)

    project_dir = create_project(workspace_root, args.project)
    print(f"Project created: {project_dir}")
    print()
    print("Files:")
    print(f"  {project_dir / 'project.toml'}   <- shared settings")
    print(f"  {project_dir / 'run_demo.toml'}   <- executable run")
    print()
    print("Next steps:")
    print("  1. Edit project.toml with your geographic/domain/flow settings")
    print(f"  2. Run: hmp run {project_dir / 'run_demo.toml'}")
