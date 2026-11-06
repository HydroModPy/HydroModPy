"""``hmp catalog trash`` - list the project trash, or empty it."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from hydromodpy.cli.conventions import (
    confirm_parser,
    dry_run_parser,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import confirm, project_root_of
from hydromodpy.cli.output import emit

NAME: str = "trash"
HELP: str = "List the trash of a project, or remove its entries for good with --empty"


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
        epilog=(
            "Each removed entry leaves a line in trash/tombstones.txt, so its name\n"
            "is never given to a new run.\n"
            "\n"
            "Examples:\n"
            "  hmp catalog trash\n"
            "  hmp catalog trash --empty --dry-run\n"
            "  hmp catalog trash --empty --force -y"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--empty",
        action="store_true",
        help="Remove every trashed directory for good (frees disk, leaves tombstones)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Go past the pin: remove the pinned directories too when emptying",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.results.trash import is_protected, list_trash, purge_trashed

    root = project_root_of(args)
    entries = list_trash(root)
    if args.empty:
        doomed = [entry for entry in entries if args.force or not is_protected(entry.path)]
        if not args.dry_run:
            confirm(
                args,
                f"Remove {len(doomed)} trashed director{'y' if len(doomed) == 1 else 'ies'} for good?",
                doing="empty the trash",
            )
            purge_trashed(root, doomed, now=datetime.now(UTC))
        kept = len(entries) - len(doomed)

        def said() -> None:
            verb = "would remove" if args.dry_run else "removed"
            suffix = f" ({kept} pinned kept; --force removes them)" if kept else ""
            noun = "directory" if len(doomed) == 1 else "directories"
            print(f"{verb} {len(doomed)} trashed {noun}{suffix}.")

        emit(
            args,
            "catalog trash empty",
            {
                "applied": not args.dry_run,
                "removed": [entry.rel_dir for entry in doomed],
                "kept_pinned": kept,
            },
            table=said,
        )
        return

    def table() -> None:
        if not entries:
            print("trash is empty.")
            return
        print(f"# trash ({len(entries)} entr{'y' if len(entries) == 1 else 'ies'})")
        for entry in entries:
            print(f"  {entry.rel_dir}  {entry.trashed_at:%Y-%m-%d %H:%M}  {entry.name}")

    emit(
        args,
        "catalog trash",
        [
            {"name": entry.name, "rel_dir": entry.rel_dir, "trashed_at": entry.trashed_at}
            for entry in entries
        ],
        table=table,
    )
