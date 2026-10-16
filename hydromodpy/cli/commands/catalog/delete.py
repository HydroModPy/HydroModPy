"""``hmp catalog delete`` - move a run or a session to the project trash."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from hydromodpy.cli._conventions import (
    add_sim_ref,
    confirm_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import EXIT_SIGINT, EXIT_USAGE, apply_verbosity, exit_code_for
from hydromodpy.core.state.paths import catalog_path_for, resolve_project_root

NAME: str = "delete"
HELP: str = "Move a run or a session to the trash (reversible); --now to remove it for good"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), confirm_parser(), verbosity_parser()],
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
        help="Act on a pinned directory, or on one whose attempt stopped beating (stale)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.results.catalog.discovery import resolve_rel_dir
    from hydromodpy.results.trash import list_trash, purge_trashed, trash_run

    root = resolve_project_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    try:
        rel_dir = resolve_rel_dir(root, args.sim_ref, site=args.site, unambiguous=True)
    except Exception as exc:  # noqa: BLE001 - map resolver errors to typed exit codes
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))

    verb = "Remove for good" if args.now else "Trash"
    if not args.yes:
        if not sys.stdin.isatty():
            print(
                f"Refusing to {verb.lower()} without -y in non-interactive mode.", file=sys.stderr
            )
            sys.exit(EXIT_USAGE)
        try:
            resp = input(f"{verb} {rel_dir}? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            sys.exit(EXIT_SIGINT)
        if resp not in {"y", "yes"}:
            print("Aborted.", file=sys.stderr)
            sys.exit(EXIT_SIGINT)

    now = datetime.now(UTC)
    try:
        trashed = trash_run(root, rel_dir, now=now, force=args.force)
        if args.now:
            entry = next(entry for entry in list_trash(root) if entry.path == trashed)
            purge_trashed(root, [entry], now=now)
    except Exception as exc:  # noqa: BLE001 - map in-use, protected and IO errors
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))
    if catalog_path_for(root).is_file():
        from hydromodpy.results.catalog.indexer import index_new_runs

        index_new_runs(root)
    if args.now:
        print(f"removed {rel_dir}; its name stays taken (trash/tombstones.txt)")
    else:
        print(f"moved {rel_dir} to trash/{trashed.name}. Restore: hmp catalog restore {rel_dir}")
