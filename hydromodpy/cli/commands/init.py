"""``hmp init`` - scaffold a HydroModPy data workspace."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_CONFIG

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

    print(f"Workspace: {result}")
    print(f"Scaffolded at {result}/. Create projects with `hmp new <name> --workspace {result}`.")
    print()
    print("Layout:")
    print(f"  {result}/data/")
    print(f"  {result}/projects/")
    print("  <project>/hydromodpy.duckdb")
    print("  <project>/simulations/")
