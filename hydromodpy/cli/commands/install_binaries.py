"""``hmp install-binaries`` - pre-warm the solver binary cache.

Wraps :func:`hydromodpy.solver.modflow_common.binaries.download_solver_binaries`
via the ``_workers.dev`` helper. Binaries also download lazily on first solver
use, so this verb is only needed to pre-fetch them (e.g. for offline runs).
"""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import (
    add_destination,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import EXIT_CONFIG, apply_verbosity, refuse
from hydromodpy.cli.output import emit
from hydromodpy.core.console import progress

NAME: str = "install-binaries"
HELP: str = "Download MODFLOW/MODPATH/MT3D-USGS binaries into the HydroModPy cache"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(reads_none=True), format_parser(), verbosity_parser()],
        epilog="Examples:\n  hmp install-binaries\n  hmp install-binaries --subset mf6,mfnwt\n  hmp install-binaries --mf6-prt",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--subset", default=None, help="Comma-separated solver names (default: all)"
    )
    parser.add_argument(
        "--mf6-prt",
        action="store_true",
        help="Install only the MODFLOW 6 executable used by MF6-PRT",
    )
    add_destination(parser, help="Target directory", metavar="DIR")
    parser.add_argument(
        "--release",
        default=None,
        help="MODFLOW-ORG release tag. Only a release whose sha256 HydroModPy pins is installed",
    )
    parser.add_argument("--upgrade", action="store_true", help="Download again")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.dev import install_binaries

    apply_verbosity(args, {})
    subset = (
        [name.strip() for name in args.subset.split(",") if name.strip()] if args.subset else None
    )
    try:
        with progress.status("Downloading MODFLOW binaries"):
            result = install_binaries(
                subset=subset,
                mf6_prt=args.mf6_prt,
                bindir=args.to,
                upgrade=args.upgrade,
                quiet=args.verbosity == "quiet",
                release=args.release,
            )
    except (RuntimeError, ValueError) as exc:
        refuse(f"[install-binaries] {exc}", EXIT_CONFIG, cause=exc)

    def table() -> None:
        if result["already_cached"]:
            print(
                f"[install-binaries] Already cached (release={result['release']}). "
                "Use --upgrade to re-download."
            )
            return
        action = "Upgraded" if args.upgrade else "Installed"
        print(
            f"[install-binaries] {action} {result['installed']} "
            f"(release={result['release']}) into {result['target']}"
        )

    emit(args, "install-binaries", result, table=table)
