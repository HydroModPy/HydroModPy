"""``hmp catalog trash`` - list the project trash, or empty it."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from hydromodpy.cli.conventions import format_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import apply_verbosity, exit_code_for
from hydromodpy.core.state.paths import resolve_project_root

NAME: str = "trash"
HELP: str = "List the trash of a project, or remove its entries for good with --empty"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog=(
            "Each removed entry leaves a line in trash/tombstones.txt, so its name\n"
            "is never given to a new run.\n"
            "\n"
            "Examples:\n"
            "  hmp catalog trash\n"
            "  hmp catalog trash --empty --force"
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
        help="Include the pinned directories when emptying",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.results.trash import is_protected, list_trash, purge_trashed

    root = resolve_project_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    entries = list_trash(root)

    if args.empty:
        doomed = [entry for entry in entries if args.force or not is_protected(entry.path)]
        try:
            purged = purge_trashed(root, doomed, now=datetime.now(UTC))
        except Exception as exc:  # noqa: BLE001 - map IO errors to typed exit codes
            print(str(exc), file=sys.stderr)
            sys.exit(exit_code_for(exc))
        kept = len(entries) - len(doomed)
        suffix = f" ({kept} pinned kept; --force removes them)" if kept else ""
        print(
            f"removed {len(purged)} trashed director{'y' if len(purged) == 1 else 'ies'}{suffix}."
        )
        return

    if args.format == "json":
        import json

        rows = [
            {"name": e.name, "rel_dir": e.rel_dir, "trashed_at": e.trashed_at.isoformat()}
            for e in entries
        ]
        print(json.dumps(rows))
        return

    if not entries:
        print("trash is empty.")
        return
    print(f"# trash ({len(entries)} entr{'y' if len(entries) == 1 else 'ies'})")
    for entry in entries:
        print(f"  {entry.rel_dir}  {entry.trashed_at:%Y-%m-%d %H:%M}  {entry.name}")
