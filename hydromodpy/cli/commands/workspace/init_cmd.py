"""``hmp workspace init`` - scaffold a HydroModPy data workspace."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_CONFIG
from hydromodpy.core.state.global_index import auto_register_workspace
from hydromodpy.core.state.paths import CATALOG_FILENAME, WORKSPACE_TOML_FILENAME
from hydromodpy.core.workspace.workspace_toml import write_workspace_toml

NAME: str = "init"
HELP: str = "Scaffold a HydroModPy workspace (data + projects). Default: ~/hydromodpy/"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Workspace path (default: ~/hydromodpy/)",
    )
    parser.add_argument(
        "--path",
        dest="path_opt",
        default=None,
        help="Workspace path (alternate flag-form of the positional argument).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing workspace catalog.",
    )
    parser.add_argument(
        "--project-name",
        default=None,
        help="Workspace project name written into workspace.toml.",
    )
    parser.add_argument(
        "--creator-name",
        default=None,
        help="Workspace creator name written into workspace.toml.",
    )
    parser.add_argument(
        "--creator-email",
        default=None,
        help="Workspace creator email written into workspace.toml.",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.data.scaffold import DEFAULT_ROOT, scaffold

    resolved_path = args.path or getattr(args, "path_opt", None)
    target = Path(resolved_path).expanduser().resolve() if resolved_path else DEFAULT_ROOT
    if target.exists() and any(target.iterdir()) and not args.force:
        print(
            f"Workspace already initialized at {target}. Re-run with --force to reuse it.",
            file=sys.stderr,
        )
        sys.exit(EXIT_CONFIG)

    result = scaffold(target)
    workspace_toml = write_workspace_toml(
        result,
        project_name=args.project_name or result.name,
        creator_name=args.creator_name or "",
        creator_email=args.creator_email or "",
        force=args.force,
    )
    auto_register_workspace(result, label=args.project_name or result.name)

    print(f"Workspace: {result}")
    print(
        f"Scaffolded at {result}/. Create projects with `hmp project new <name> --workspace {result}`."
    )
    print()
    print("Layout:")
    print(f"  {result}/{WORKSPACE_TOML_FILENAME}")
    print(f"  {result}/data/")
    print(f"  {result}/projects/")
    print(f"  <project>/{CATALOG_FILENAME}")
    print("  <project>/simulations/")
    print()
    print(f"Workspace metadata: {workspace_toml}")
