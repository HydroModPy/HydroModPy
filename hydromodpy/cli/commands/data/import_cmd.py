"""``hmp data import`` - thin wrapper around :func:`hydromodpy.import_package`."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_NOT_FOUND, EXIT_RUN_FAILED

NAME: str = "import"
HELP: str = "Import a .hmp archive and dematerialise its bundled inputs"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("package", help="Path to the .hmp archive")
    parser.add_argument("-w", "--workspace", default=None, help="Target project catalog root")
    parser.add_argument(
        "--as", dest="as_project", default=None, help="Override the project name on import"
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing sim_id")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    import hydromodpy as hmp
    from hydromodpy.results.importers import InputCollisionError

    try:
        sim_id = hmp.import_package(
            args.package,
            workspace=args.workspace,
            as_project=args.as_project,
            dry_run=args.dry_run,
            force=args.force,
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
        print(f"Dry-run OK. Archive would import sim {sim_id}")
    else:
        print(f"Imported {sim_id}")
