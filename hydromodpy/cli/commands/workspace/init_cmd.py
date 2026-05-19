"""``hmp workspace init`` - thin wrapper around :func:`hydromodpy.init_workspace`."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_CONFIG
from hydromodpy.core.state.paths import CATALOG_FILENAME, WORKSPACE_TOML_FILENAME

NAME: str = "init"
HELP: str = "Scaffold a HydroModPy workspace (data + projects). Default: ~/hydromodpy/"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("path", nargs="?", default=None, help="Workspace path")
    parser.add_argument("--path", dest="path_opt", default=None, help="Alternate flag-form")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing workspace")
    parser.add_argument("--project-name", default=None)
    parser.add_argument("--creator-name", default=None)
    parser.add_argument("--creator-email", default=None)
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    import hydromodpy as hmp

    resolved = args.path or getattr(args, "path_opt", None)
    try:
        result = hmp.init_workspace(
            resolved,
            force=args.force,
            project_name=args.project_name,
            creator_name=args.creator_name,
            creator_email=args.creator_email,
        )
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    target = result["path"]
    print(f"Workspace: {target}")
    print(f"Scaffolded at {target}/. Create projects with 'hmp project new <name>'.")
    print()
    print("Layout:")
    print(f"  {target}/{WORKSPACE_TOML_FILENAME}")
    print(f"  {target}/data/")
    print(f"  {target}/projects/")
    print(f"  <project>/{CATALOG_FILENAME}")
    print()
    print(f"Workspace metadata: {result['workspace_toml']}")
