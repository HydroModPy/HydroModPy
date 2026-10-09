"""``hmp workspace clean`` - thin wrapper around :func:`hydromodpy.clean_workspace`."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND

NAME: str = "clean"
HELP: str = "Remove generated workspace artifacts"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        epilog="Examples:\n  hmp workspace clean --results --dry-run\n  hmp workspace clean --all -y",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--workspace", default=None, help="Workspace root")
    parser.add_argument(
        "--all", action="store_true", dest="all_groups", help="Clean every group below"
    )
    parser.add_argument(
        "--results", action="store_true", help="The index database and the runs/ tree"
    )
    parser.add_argument(
        "--data-cache", action="store_true", dest="data_cache", help="The data cache"
    )
    parser.add_argument("--runtime", action="store_true", help="The .hmp/ runtime folder")
    parser.add_argument("--share", action="store_true", help="The published share/ tree")
    parser.add_argument("--scratch", action="store_true", help="The scratch folders (.hmp/scratch)")
    parser.add_argument(
        "--figures", action="store_true", help="The share/figures folders of the projects"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="List what would be removed and remove nothing (the default unless -y is given)",
    )
    parser.add_argument("-y", "--yes", action="store_true", help="Delete without dry-run")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.workspace import CLEAN_GROUPS, clean_workspace

    groups = {"all"} if args.all_groups else set()
    for name in CLEAN_GROUPS:
        if getattr(args, name, False):
            groups.add(name)
    dry_run = bool(args.dry_run) or not args.yes

    try:
        result = clean_workspace(args.workspace, groups=groups, dry_run=dry_run)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    candidates = result["candidates"]
    if not candidates:
        print(f"No generated artifacts found in {result['workspace']}.")
        return
    label = "Dry-run, would delete" if dry_run else "Deleting"
    print(f"{label} {len(candidates)} path(s) in {result['workspace']}:")
    for target in candidates:
        print(f"  {target}")
    if dry_run:
        print("Re-run with --yes to delete.")
