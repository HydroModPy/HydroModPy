"""``hmp install-binaries`` - thin wrapper around :func:`hydromodpy.install_binaries`."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_OK

NAME: str = "install-binaries"
HELP: str = "Download MODFLOW/MODPATH/MT3D-USGS binaries into the HydroModPy cache"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "--subset", default=None, help="Comma-separated solver names (default: all)"
    )
    parser.add_argument(
        "--mf6-prt",
        action="store_true",
        help="Install only the MODFLOW 6 executable used by MF6-PRT",
    )
    parser.add_argument("--bindir", default=None, help="Target directory")
    parser.add_argument("--release", default=None, help="MODFLOW-ORG release tag")
    parser.add_argument(
        "--upgrade", "--force", dest="upgrade", action="store_true", help="Re-download"
    )
    parser.add_argument("--quiet", action="store_true", help="Reduce progress output")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.dev import install_binaries

    subset = (
        [name.strip() for name in args.subset.split(",") if name.strip()] if args.subset else None
    )
    try:
        result = install_binaries(
            subset=subset,
            mf6_prt=args.mf6_prt,
            bindir=args.bindir,
            upgrade=args.upgrade,
            quiet=args.quiet,
            release=args.release,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"[install-binaries] {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    if result["already_cached"]:
        print(
            f"[install-binaries] Already cached (release={result['release']}). "
            "Use --upgrade to re-download."
        )
    else:
        action = "Upgraded" if args.upgrade else "Installed"
        print(
            f"[install-binaries] {action} {result['installed']} "
            f"(release={result['release']}) into {result['target']}"
        )
    sys.exit(EXIT_OK)
