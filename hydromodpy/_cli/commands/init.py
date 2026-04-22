"""``hmp init`` — scaffold a HydroModPy workspace."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy._cli.helpers import EXIT_CONFIG


NAME = "init"
HELP = "Scaffold a HydroModPy workspace (catalog + data + projects). Default: ~/hydromodpy/"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "path", nargs="?", default=None,
        help="Workspace path (default: ~/hydromodpy/)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite an existing workspace catalog.",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.data.scaffold import DEFAULT_ROOT, scaffold

    target = Path(args.path).expanduser().resolve() if args.path else DEFAULT_ROOT
    catalog = target / "hydromodpy.duckdb"
    if catalog.exists() and not args.force:
        print(
            f"Workspace already initialized at {target} "
            f"(found {catalog.name}). Re-run with --force to overwrite.",
            file=sys.stderr,
        )
        sys.exit(EXIT_CONFIG)

    result = scaffold(target, force=args.force)

    print(f"Workspace scaffolded at {result}/. Create projects with "
          f"`hmp new <name> --workspace {result}`.")
    print()
    print("Layout:")
    print(f"  {result}/hydromodpy.duckdb")
    print(f"  {result}/data/")
    print(f"  {result}/projects/")
    print(f"  {result}/simulations/")
