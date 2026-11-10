"""``hmp stop REF`` - ask a running run or calibration session to stop.

The command writes the stop flag ``<dir>/.hmp/stop.json`` through
:func:`hydromodpy.project.api.stop`, the verb ``hmp.stop``, and returns at once. The run reads the flag at its next
check, ends ``aborted``, and its own process exits with 130, the code of an
interruption. ``hmp run --resume REF`` takes it up again.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.conventions import format_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.output import emit
from hydromodpy.core.state.result_dirs import resolve_project_root

NAME: str = "stop"
HELP: str = "Ask a running run or calibration session to stop"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog="Examples:\n  hmp stop baseline\n  hmp stop sessions/calibration.v2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "ref",
        metavar="REF",
        help=(
            "A running run, <name>[.vN] or runs/<name>[.vN] (a bare name is its "
            "latest version), or a running calibration session, sessions/<case>[.vN]."
        ),
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.project.api import stop

    workspace = args.workspace or resolve_project_root(Path.cwd())
    flag = stop(args.ref, workspace=workspace)
    emit(
        args,
        "stop",
        {"ref": args.ref, "flag": flag},
        table=lambda: print(f"asked {args.ref} to stop ({flag})", file=sys.stderr),
    )
