"""``hmp data prune`` - drop the old rows of the cache, never a file a run or a lockfile cites."""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import (
    confirm_parser,
    dry_run_parser,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import confirm
from hydromodpy.cli.output import emit

NAME: str = "prune"
HELP: str = "Drop cache rows older than N days, except the files a run or a lockfile cites"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[
            workspace_parser(),
            confirm_parser(),
            dry_run_parser(),
            format_parser(),
            verbosity_parser(),
        ],
        epilog="Example:\n  hmp data prune --older-than 90 --delete-files -y",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--older-than", type=int, default=30, help="Age threshold in days (default: 30)"
    )
    parser.add_argument(
        "--delete-files",
        action="store_true",
        help="Also delete the files. Without it only the sidecars go, and the files are no rows",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli.helpers import resolve_workspace
    from hydromodpy.project.data_cache import prune_data

    workspace = resolve_workspace(args.workspace)
    options = {"older_than_days": args.older_than, "delete_files": args.delete_files}
    if not args.dry_run:
        # The dry run reads every run and lockfile first, so one that cannot be read
        # refuses here, before anything is asked or removed.
        preview = prune_data(workspace, dry_run=True, **options)
        confirm(
            args,
            f"Drop {len(preview.removed)} cache row(s) older than {args.older_than} day(s)?",
            doing="prune the cache",
        )
    report = prune_data(workspace, dry_run=args.dry_run, **options)
    removed, kept = len(report.removed), [str(path) for path in report.kept_cited]
    verb = "Would prune" if args.dry_run else "Pruned"

    def table() -> None:
        print(f"  {verb} {removed} row(s) older than {args.older_than} day(s).")
        if report.orphans:
            leaves = "would leave" if args.dry_run else "left"
            print(f"  {len(report.orphans)} sidecar(s) without a file {leaves} the cache.")
        if kept:
            print(f"  Kept {len(kept)} file(s) that a run or a lockfile cites:")
            for path in kept:
                print(f"    {path}")

    emit(
        args,
        "data prune",
        {
            "applied": not args.dry_run,
            "older_than_days": args.older_than,
            "removed": removed,
            "kept": kept,
            "orphans": len(report.orphans),
            "user_files": report.user_files,
        },
        table=table,
    )
