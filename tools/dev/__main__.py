"""Entry point: ``python -m tools.dev``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from hydromodpy.cli.conventions import HmpParser, verbosity_parser
from hydromodpy.cli.helpers import apply_verbosity, fail
from hydromodpy.core.io.proj_bootstrap import bootstrap_proj
from hydromodpy.core.runtime.bootstrap_hook import ensure_bootstrapped
from tools.dev import examples, run_script, test

ACTIONS = (test, run_script, examples)


def build_parser() -> argparse.ArgumentParser:
    parser = HmpParser(
        prog="python -m tools.dev",
        description="Developer commands for a checkout of HydroModPy.",
        parents=[verbosity_parser()],
    )
    sub = parser.add_subparsers(dest="action", metavar="<action>", required=True)
    for action in ACTIONS:
        action.register(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else list(argv))
    # Set the process up as hmp does: the pytest and script children inherit PROJ_DATA.
    ensure_bootstrapped()
    bootstrap_proj()
    try:
        # The flag, else HMP_VERBOSITY.
        apply_verbosity(args, {})
        args._handler(args)
    except SystemExit:
        raise
    except BaseException as exc:
        fail(exc)


if __name__ == "__main__":
    main()
