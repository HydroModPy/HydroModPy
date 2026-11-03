"""``hmp viz regen`` - draw again the figures ``figures/index.json`` of a run records.

Each figure is drawn with the options it was recorded with, into the same
file under ``runs/<run>/figures/``, and recorded again with the identity of
the run on the day.
"""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.conventions import add_sim_ref, verbosity_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, apply_verbosity, exit_code_for

NAME: str = "regen"
HELP: str = "Draw again the figures a run's figures/index.json records"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[verbosity_parser()],
        epilog="Example:\n  hmp viz regen baseline_monthly",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_sim_ref(parser)
    parser.add_argument("-w", "--workspace", default=None, help="Project catalog root")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.cli._workers.viz import regen_figures
    from hydromodpy.results.catalog import AmbiguousReferenceError, SimulationNotFoundError

    try:
        written = regen_figures(args.sim_ref, workspace=args.workspace)
    except (AmbiguousReferenceError, SimulationNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except Exception as exc:  # noqa: BLE001 - mapped to a typed exit code below
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))
    for path in written:
        print(path)
    print(f"Drew {len(written)} figure(s) again", file=sys.stderr)
