"""``hmp add`` - import a .hmp archive and its bundled inputs into a workspace."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_NOT_FOUND, EXIT_RUN_FAILED

NAME: str = "add"
HELP: str = "Import a .hmp archive and dematerialise its bundled inputs"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("package", help="Path to the .hmp archive")
    parser.add_argument(
        "-w",
        "--workspace",
        default=None,
        help="Target workspace root (default: current directory)",
    )
    parser.add_argument(
        "--as",
        dest="as_project",
        default=None,
        help="Override the project name on import "
        "(required when the workspace already owns a project with "
        "the incoming name)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and preview without writing anything",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing simulation with the same sim_id",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.results.catalog import SimulationCatalog
    from hydromodpy.results.importers import InputCollisionError

    src = Path(args.package).expanduser().resolve()
    if not src.is_file():
        print(f"Archive not found: {src}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    workspace_root = Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)

    with SimulationCatalog(workspace_root) as catalog:
        try:
            sim_id = catalog.import_package(
                src,
                force=args.force,
                as_project=args.as_project,
                dry_run=args.dry_run,
            )
        except InputCollisionError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(EXIT_RUN_FAILED)
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(EXIT_NOT_FOUND)
        except ValueError as exc:
            print(f"Import failed: {exc}", file=sys.stderr)
            sys.exit(EXIT_RUN_FAILED)

    if args.dry_run:
        print(f"Dry-run OK. Archive would import sim {sim_id} into {workspace_root}")
        return
    print(f"Imported {sim_id} into {workspace_root}")
