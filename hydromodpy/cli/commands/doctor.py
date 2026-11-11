"""``hmp doctor`` - diagnose the local environment.

It reads and reports. The files it rewrites are the TOML that ``--fix-config``
names and the files it inherits through ``base_config``, migrated in place to
the current grammar. The workspace is the one ``-w`` names or the one that holds the current
directory, never a default folder: without one, the workspace checks say so
and name ``-w``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.conventions import dry_run_parser, format_parser, workspace_parser
from hydromodpy.cli.exit_codes import EXIT_GENERIC, EXIT_USAGE, refuse
from hydromodpy.cli.output import emit
from hydromodpy.core.workspace.resolve import find_workspace

NAME: str = "doctor"
HELP: str = "Diagnose the local environment (Python, deps, solvers, workspace)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), dry_run_parser(), format_parser()],
        epilog=(
            "Examples:\n  hmp doctor\n  hmp doctor -w ~/hydromodpy --format json\n"
            "  hmp doctor --fix-config run.toml\n"
            "The workspace a TOML file resolves to: hmp check run.toml -v"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--cross-catalog",
        action="store_true",
        help="Cross-check the sealed runs on disk against the index of each project",
    )
    parser.add_argument(
        "--lifecycle",
        action="store_true",
        help="Surface lifecycle issues (stale attempts, abandoned sessions, tmp files)",
    )
    parser.add_argument(
        "--prt",
        action="store_true",
        help="Check that the resolved MODFLOW 6 build supports particle tracking (PRT)",
    )
    parser.add_argument(
        "--fix-config",
        default=None,
        metavar="FILE.toml",
        help=(
            "Rewrite every old key of a TOML and of the files it inherits through base_config "
            "under its current name, in place, and print what changed in each file. Preserves "
            "comments and layout. A key that still loads warns and names this option. "
            "With --dry-run it prints the diff it would write and writes nothing."
        ),
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    named = getattr(args, "fix_config", None)
    if named is not None:
        fix_config(named, dry_run=args.dry_run)
        return
    if args.dry_run:
        refuse("--dry-run goes with --fix-config: the other checks write nothing.", EXIT_USAGE)

    from hydromodpy.project.api import doctor
    from hydromodpy.project.doctor import (
        build_report,
        cross_catalog_checks,
        lifecycle_checks,
        prt_checks,
    )

    workspace = find_workspace(args.workspace)
    report = build_report(doctor().to_dict(), workspace, args.workspace)

    if getattr(args, "cross_catalog", False):
        report["checks"].extend(cross_catalog_checks(workspace))
    if getattr(args, "lifecycle", False):
        report["checks"].extend(lifecycle_checks(workspace))
    if getattr(args, "prt", False):
        report["checks"].extend(prt_checks())

    emit(args, "doctor", report, table=lambda: _print_report(report))

    if any(entry.get("status") == "KO" for entry in report["checks"]):
        sys.exit(EXIT_GENERIC)


def fix_config(toml_path: str, *, dry_run: bool = False) -> None:
    """Rewrite a TOML and the files it inherits under the current grammar."""
    from hydromodpy.cli.exit_codes import EXIT_CONFIG, EXIT_NOT_FOUND
    from hydromodpy.config.config_migration import fix_config_chain
    from hydromodpy.core.config_kit.base import CANNOT_REWRITE
    from hydromodpy.project.doctor import findings_of, refusal_in

    path = Path(toml_path).expanduser()
    diffs: dict[Path, str] = {}
    try:
        chain = fix_config_chain(path, dry_run=dry_run, diffs=diffs)
    except FileNotFoundError as exc:
        refuse(str(exc), EXIT_NOT_FOUND, cause=exc)
    except Exception as exc:  # noqa: BLE001 - surface a clean parse error
        refuse(f"Could not migrate {path}: {exc}", EXIT_CONFIG, cause=exc)

    refused: Exception | None = None
    for file, changes in chain.items():
        if not changes:
            held = findings_of(file)
            refusal = refusal_in(held)
            if refusal is not None:
                print(f"{file} has nothing to migrate, and the check still refuses it:")
                print(f"  - {refusal}")
                refused = refusal
                continue
            # Under --dry-run the files above are not rewritten yet, so their old forms
            # still show here and are told under their own file.
            left = [] if dry_run else [item for item in held if item.code == "old_key"]
            if left:
                print(f"{file} has nothing to migrate, and the check still reads old forms:")
                for item in left:
                    print(f"  - {item.detail}")
            else:
                print(f"{file} is already up to date.")
            continue
        untouched = all(CANNOT_REWRITE in change for change in changes)
        label = "Left as it is" if untouched else ("Would migrate" if dry_run else "Migrated")
        print(f"{label} {file}:")
        for change in changes:
            print(f"  - {change}")
        if dry_run and diffs.get(file):
            print(diffs[file], end="" if diffs[file].endswith("\n") else "\n")
    if refused is not None:
        sys.exit(EXIT_CONFIG)


def _print_report(report: dict) -> None:
    print(f"Python     : {report['python']}")
    print(f"Platform   : {report['platform']}")
    print(f"HydroModPy : {report['hydromodpy']}")
    print()
    print(f"{'STATUS':<6} {'CHECK':<28} DETAIL")
    print("-" * 70)
    for entry in report["checks"]:
        status = entry["status"]
        marker = {"OK": "OK", "WARN": "WARN", "KO": "KO"}.get(status, status)
        print(f"{marker:<6} {entry['name']:<28} {entry['detail']}")
        if entry.get("hint") and status != "OK":
            print(f"       -> {entry['hint']}")
