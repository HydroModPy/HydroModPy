"""``hmp catalog restore`` - bring a trashed simulation back."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli._conventions import add_sim_ref, workspace_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, exit_code_for
from hydromodpy.core.state.paths import resolve_project_root

NAME: str = "restore"
HELP: str = "Restore a trashed simulation (auto-versions if the name was reused)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser()],
        epilog="Example:\n  hmp catalog restore d11b32c8",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_sim_ref(parser, help="Trashed run reference (id8 or UUID; trashed runs have no name)")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.catalog import restore_simulation

    workspace_root = resolve_project_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    try:
        result = restore_simulation(args.sim_ref, workspace=workspace_root)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except Exception as exc:  # noqa: BLE001 - map resolver errors to typed exit codes
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))

    print(f"restored as {result['name']}  [{result['sim_id'][:8]}]")
