"""``hmp catalog adopt`` - re-register an orphan store into the catalog."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli._conventions import workspace_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, exit_code_for, find_catalog_root

NAME: str = "adopt"
HELP: str = "Re-register an orphan store (present on disk, missing from the catalog)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser()],
        epilog="Example:\n  hmp catalog adopt simulations/cheze__9c41aa02.parquet",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("store", help="Path to the orphan .zarr / .zarr.zip / .parquet store")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.catalog import adopt_store

    workspace_root = find_catalog_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    try:
        result = adopt_store(args.store, workspace=workspace_root)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except Exception as exc:  # noqa: BLE001 - map adoption errors to typed exit codes
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))

    print(f"adopted [{result['sim_id'][:8]}] from {args.store}")
