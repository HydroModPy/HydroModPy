"""``hmp catalog note`` - append a timestamped note to a simulation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli._conventions import add_sim_ref, workspace_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, exit_code_for, find_catalog_root

NAME: str = "note"
HELP: str = "Append a timestamped note to a simulation"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser()],
        epilog='Example:\n  hmp catalog note ab12cd34 "best fit after widening Sy bounds"',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_sim_ref(parser)
    parser.add_argument("text", help="Note text")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.catalog import note_simulation

    workspace_root = find_catalog_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    try:
        result = note_simulation(args.sim_ref, workspace=workspace_root, note=args.text)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except Exception as exc:  # noqa: BLE001 - map resolver errors to typed exit codes
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))

    print(f"noted [{result['sim_id'][:8]}]")
