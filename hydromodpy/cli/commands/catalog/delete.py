"""``hmp catalog delete`` - move a run or a session to the project trash."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from hydromodpy.cli.conventions import (
    add_sim_ref,
    confirm_parser,
    dry_run_parser,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import apply_verbosity, confirm, project_root_of
from hydromodpy.cli.output import emit
from hydromodpy.core.state.layout import catalog_path_for

NAME: str = "delete"
HELP: str = "Move a run or a session to the trash (reversible); --now to remove it for good"


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
            "The reference is the directory: a bare name is runs/<name> exactly, and\n"
            "a bare name whose stem has other versions is refused with the list.\n"
            "\n"
            "Examples:\n"
            "  hmp catalog delete baseline.v2 -y\n"
            "  hmp catalog delete sessions/calibration -y\n"
            "  hmp catalog delete baseline_daily --now -y"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_sim_ref(parser)
    parser.add_argument(
        "--site",
        default=None,
        help="Narrow an @-selector (@last, @best:nse) to the runs of one site",
    )
    parser.add_argument(
        "--now",
        action="store_true",
        help="Remove the directory for good: a tombstone keeps its name from being reused",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Go past the pin and the stale attempt: act on a pinned directory, or on one whose "
        "attempt stopped beating",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.results.catalog.discovery import resolve_rel_dir
    from hydromodpy.results.trash import list_trash, purge_trashed, trash_run

    root = project_root_of(args)
    rel_dir = resolve_rel_dir(root, args.sim_ref, site=args.site, unambiguous=True)
    facts = {"rel_dir": rel_dir, "removed_for_good": args.now}
    if args.dry_run:
        verb = "remove for good" if args.now else "move to the trash"
        emit(
            args,
            "catalog delete",
            {**facts, "applied": False},
            table=lambda: print(f"would {verb} {rel_dir}"),
        )
        return
    verb = "Remove for good" if args.now else "Trash"
    confirm(args, f"{verb} {rel_dir}?", doing=verb.lower())

    now = datetime.now(UTC)
    trashed = trash_run(root, rel_dir, now=now, force=args.force)
    if args.now:
        entry = next(entry for entry in list_trash(root) if entry.path == trashed)
        purge_trashed(root, [entry], now=now)
    if catalog_path_for(root).is_file():
        from hydromodpy.results.catalog.indexer import index_new_runs

        index_new_runs(root)

    def table() -> None:
        if args.now:
            print(f"removed {rel_dir}; its name stays taken (trash/tombstones.txt)")
        else:
            print(
                f"moved {rel_dir} to trash/{trashed.name}. Restore: hmp catalog restore {rel_dir}"
            )

    emit(
        args,
        "catalog delete",
        {**facts, "applied": True, "trashed_to": None if args.now else trashed},
        table=table,
    )
