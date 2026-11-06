"""``hmp install-binaries`` - pre-warm the solver binary cache.

Wraps :func:`hydromodpy.solver.modflow_common.binaries.download_solver_binaries`
through ``_install_binaries``. Binaries also download lazily on first solver
use, so this verb is only needed to pre-fetch them (e.g. for offline runs).
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from hydromodpy.cli.conventions import (
    add_destination,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import EXIT_CONFIG, refuse
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


def _install_binaries(
    *,
    subset: list[str] | None = None,
    mf6_prt: bool = False,
    bindir: Any = None,
    upgrade: bool = False,
    quiet: bool = False,
    release: str | None = None,
) -> dict:
    """Pre-warm the MODFLOW / MODPATH / MT3D-USGS binary cache."""
    from hydromodpy.solver.modflow_common.binaries import (
        DEFAULT_RELEASE,
        available_solvers,
        download_solver_binaries,
        locate_solver_binary,
        managed_bin_dir,
        read_manifest,
    )

    target = Path(bindir).expanduser().resolve() if bindir else managed_bin_dir()
    resolved_release = release or DEFAULT_RELEASE

    if mf6_prt:
        names = ["mf6"]
    elif subset:
        names = list(subset)
    else:
        names = list(available_solvers())

    manifest = read_manifest(target)
    cached = (
        manifest is not None
        and manifest.get("release") == resolved_release
        and set(names).issubset(set(manifest.get("solvers", [])))
        and all(locate_solver_binary(target, name) is not None for name in names)
    )

    if cached and not upgrade:
        return {
            "already_cached": True,
            "release": resolved_release,
            "installed": [],
            "target": str(target),
        }

    final_target = download_solver_binaries(
        bindir=target,
        subset=names,
        quiet=quiet,
        force=upgrade,
        release=resolved_release,
    )
    return {
        "already_cached": False,
        "release": resolved_release,
        "installed": names,
        "target": str(final_target),
    }


def run(args: argparse.Namespace) -> None:
    subset = (
        [name.strip() for name in args.subset.split(",") if name.strip()] if args.subset else None
    )
    try:
        with progress.status("Downloading MODFLOW binaries"):
            result = _install_binaries(
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
