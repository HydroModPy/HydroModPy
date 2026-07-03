"""``hmp catalog delete`` - thin wrapper around the ``catalog`` worker."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli._conventions import add_sim_ref, confirm_parser, workspace_parser
from hydromodpy.cli.helpers import (
    EXIT_NOT_FOUND,
    EXIT_SIGINT,
    EXIT_USAGE,
    find_catalog_root,
)

NAME: str = "delete"
HELP: str = "Move a simulation to the trash (reversible); --now to purge permanently"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), confirm_parser()],
        epilog="Examples:\n  hmp catalog delete ab12cd34 -y\n  hmp catalog delete ab12cd34 --now -y",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_sim_ref(parser)
    parser.add_argument(
        "--now",
        action="store_true",
        help="Permanently purge now (cascade + remove storage) instead of trashing",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Act on a pinned run",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.catalog import delete_simulation, trash_simulation
    from hydromodpy.cli.helpers import exit_code_for

    workspace_root = find_catalog_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )

    verb = "Permanently purge" if args.now else "Trash"
    if not args.yes:
        if not sys.stdin.isatty():
            print(
                f"Refusing to {verb.lower()} without -y in non-interactive mode.", file=sys.stderr
            )
            sys.exit(EXIT_USAGE)
        try:
            resp = input(f"{verb} simulation {args.sim_ref!r}? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            sys.exit(EXIT_SIGINT)
        if resp not in {"y", "yes"}:
            print("Aborted.", file=sys.stderr)
            sys.exit(EXIT_SIGINT)

    try:
        if args.now:
            result = delete_simulation(args.sim_ref, workspace=workspace_root, keep_storage=False)
            for removed_path in result["removed_paths"]:
                print(f"  removed: {removed_path}")
            print(f"Purged simulation {result['sim_id']}")
        else:
            result = trash_simulation(args.sim_ref, workspace=workspace_root, force=args.force)
            sid8 = result["sim_id"][:8]
            print(
                f"moved to trash [{sid8}]. Bytes freed at 'hmp catalog trash --empty'. "
                f"Restore: hmp catalog restore {sid8}"
            )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except Exception as exc:  # noqa: BLE001 - map PinnedRunError / resolver errors
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))
