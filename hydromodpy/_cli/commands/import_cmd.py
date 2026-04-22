"""``hmp import`` — import a .hmp package into a workspace."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy._cli.helpers import EXIT_NOT_FOUND, EXIT_RUN_FAILED

NAME = "import"
HELP = "Import a .hmp package into a workspace"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("package", help="Path to the .hmp package")
    parser.add_argument(
        "-w",
        "--workspace",
        default=None,
        help="Target workspace root (default: cwd)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.results.catalog import SimulationCatalog

    src = Path(args.package).expanduser().resolve()
    if not src.is_file():
        print(f"Package not found: {src}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    workspace_root = Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)

    with SimulationCatalog(workspace_root) as catalog:
        try:
            new_ids = catalog.import_package(src)
        except Exception as exc:
            print(f"Import failed: {exc}", file=sys.stderr)
            sys.exit(EXIT_RUN_FAILED)
    if isinstance(new_ids, str):
        new_ids = [new_ids]
    print(f"Imported {len(new_ids)} simulation(s) into {workspace_root}")
    for sid in new_ids:
        print(f"  {sid}")
