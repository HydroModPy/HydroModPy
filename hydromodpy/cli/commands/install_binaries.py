"""``hmp install-binaries`` - pre-populate the solver binary cache.

By default solver binaries download lazily on first use. This command
pre-warms the cache (``~/.cache/hydromodpy/bin/`` and platform
equivalents) so subsequent runs go offline-safe. Useful for CI, air-gapped
deployments, and team laptops before handing them out.
"""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_OK

NAME: str = "install-binaries"
HELP: str = "Download MODFLOW/MODPATH/MT3D-USGS binaries into the HydroModPy cache"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "--subset",
        default=None,
        help="Comma-separated solver names to install (default: all). Example: --subset mf6,mfnwt",
    )
    parser.add_argument(
        "--bindir",
        default=None,
        help="Target directory (default: HydroModPy-managed cache).",
    )
    parser.add_argument(
        "--release",
        default=None,
        help="MODFLOW-ORG/executables release tag (default: HydroModPy pinned release).",
    )
    parser.add_argument(
        "--upgrade",
        "--force",
        dest="upgrade",
        action="store_true",
        help="Re-download even if the binaries are already cached.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce download progress output.",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.solver.modflow_common.binaries import (
        DEFAULT_RELEASE,
        available_solvers,
        download_solver_binaries,
        read_manifest,
    )

    if args.subset:
        subset = [name.strip() for name in args.subset.split(",") if name.strip()]
        known = set(available_solvers())
        unknown = [name for name in subset if name not in known]
        if unknown:
            print(
                f"[install-binaries] Unknown solver(s): {unknown}\n"
                f"Expected subset of {sorted(known)}",
                file=sys.stderr,
            )
            sys.exit(EXIT_CONFIG)
    else:
        subset = None

    manifest = read_manifest(args.bindir)
    if manifest and not args.upgrade:
        already = set(manifest.get("solvers") or [])
        requested = set(subset or available_solvers())
        if requested.issubset(already):
            print(
                f"[install-binaries] Already cached (release={manifest.get('release')}, "
                f"downloaded_at={manifest.get('downloaded_at')}). "
                f"Use --upgrade to re-download."
            )
            sys.exit(EXIT_OK)

    release = args.release or DEFAULT_RELEASE
    try:
        target = download_solver_binaries(
            bindir=args.bindir,
            subset=subset,
            quiet=args.quiet,
            force=args.upgrade,
            release=release,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"[install-binaries] {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    action = "Upgraded" if args.upgrade else "Installed"
    print(
        f"[install-binaries] {action} {subset or list(available_solvers())} "
        f"(release={release}) into {target}"
    )
    sys.exit(EXIT_OK)
