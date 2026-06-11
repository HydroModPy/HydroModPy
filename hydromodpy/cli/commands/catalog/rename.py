"""``hmp catalog rename`` - rename a simulation (pure catalog UPDATE)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli._conventions import add_sim_ref, workspace_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, exit_code_for, find_catalog_root

NAME: str = "rename"
HELP: str = "Rename a simulation (the storage basename is id-only and never moves)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser()],
        epilog="Example:\n  hmp catalog rename ab12cd34 cheze_final",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_sim_ref(parser)
    parser.add_argument("new_name", help="New simulation name")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.catalog import rename_simulation

    workspace_root = find_catalog_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    try:
        result = rename_simulation(args.sim_ref, workspace=workspace_root, new_name=args.new_name)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except Exception as exc:  # noqa: BLE001 - map resolver/collision errors to exit codes
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))

    print(f"renamed to {result['name']}  [{result['sim_id'][:8]}]")
