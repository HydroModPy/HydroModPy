"""``hmp catalog trash`` - list trashed runs or empty the trash."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli._conventions import workspace_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, find_catalog_root

NAME: str = "trash"
HELP: str = "List trashed runs, or permanently empty the trash with --empty"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser()],
        epilog="Examples:\n  hmp catalog trash\n  hmp catalog trash --empty --force",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--empty",
        action="store_true",
        help="Permanently delete trashed runs (frees disk)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Include pinned runs when emptying",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.catalog import empty_trashed, list_trashed

    workspace_root = find_catalog_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )

    if args.empty:
        try:
            purged = empty_trashed(workspace_root, force=args.force)
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(EXIT_NOT_FOUND)
        print(f"purged {len(purged)} run(s) from trash.")
        return

    try:
        entries = list_trashed(workspace_root)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    if not entries:
        print("trash is empty.")
        return
    print(f"# trash ({len(entries)} run(s))")
    for entry in entries:
        when = str(entry["trashed_at"])[:19]
        print(f"  {entry['original_name'] or '(no name)'}  [{entry['sim_id'][:8]}]  {when}")
