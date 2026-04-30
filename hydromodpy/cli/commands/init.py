"""``hmp init`` - scaffold a HydroModPy workspace."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_CONFIG

NAME: str = "init"
HELP: str = "Scaffold a HydroModPy workspace (catalog + data + projects). Default: ~/hydromodpy/"


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
    from hydromodpy.results.catalog import SimulationCatalog

    resolved_path = args.path or getattr(args, "path_opt", None)
    target = Path(resolved_path).expanduser().resolve() if resolved_path else DEFAULT_ROOT
    catalog = target / "hydromodpy.duckdb"
    if catalog.exists() and not args.force:
        print(
            f"Workspace already initialized at {target} "
            f"(found {catalog.name}). Re-run with --force to overwrite.",
            file=sys.stderr,
        )
        sys.exit(EXIT_CONFIG)

    result = scaffold(target)

    if args.force and catalog.exists():
        catalog.unlink()
    if not catalog.exists():
        with SimulationCatalog(result):
            pass

    print(f"Workspace: {result}")
    print(f"Scaffolded at {result}/. Create projects with `hmp new <name> --workspace {result}`.")
    print()
    print("Layout:")
    print(f"  {result}/hydromodpy.duckdb")
    print(f"  {result}/data/")
    print(f"  {result}/projects/")
    print(f"  {result}/simulations/")
