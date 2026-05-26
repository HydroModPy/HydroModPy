"""``hmp catalog delete`` - thin wrapper around the ``catalog`` worker."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.helpers import (
    EXIT_NOT_FOUND,
    EXIT_SIGINT,
    find_catalog_root,
)

NAME: str = "delete"
HELP: str = "Delete a simulation (DuckDB row + Zarr store)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("sim_id", help="Full sim_id, unique prefix, or simulation name")
    parser.add_argument("--workspace", default=None, help="Project catalog root")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    parser.add_argument(
        "--keep-storage",
        action="store_true",
        help="Drop catalog rows but keep Zarr/Parquet on disk",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.catalog import delete_simulation

    workspace_root = find_catalog_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )

    if not args.yes:
        if not sys.stdin.isatty():
            print("Refusing to delete without -y in non-interactive mode.", file=sys.stderr)
            sys.exit(EXIT_SIGINT)
        try:
            resp = input(f"Delete simulation {args.sim_id!r}? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            sys.exit(EXIT_SIGINT)
        if resp not in {"y", "yes"}:
            print("Aborted.", file=sys.stderr)
            sys.exit(EXIT_SIGINT)

    try:
        result = delete_simulation(
            args.sim_id,
            workspace=workspace_root,
            keep_storage=args.keep_storage,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    for removed_path in result["removed_paths"]:
        print(f"  removed: {removed_path}")
    print(f"Deleted simulation {result['sim_id']}")
