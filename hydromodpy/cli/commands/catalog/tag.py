"""``hmp catalog tag`` - add or remove tags on a simulation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli._conventions import add_sim_ref, workspace_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, exit_code_for, find_catalog_root

NAME: str = "tag"
HELP: str = "Add or remove tags on a simulation (reserved tag: pinned)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser()],
        epilog="Example:\n  hmp catalog tag ab12cd34 pinned paper --rm draft",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_sim_ref(parser)
    parser.add_argument(
        "add_tags",
        nargs="*",
        metavar="TAG",
        help="Tags to add (a leading + is optional)",
    )
    parser.add_argument(
        "--rm",
        action="append",
        default=[],
        metavar="TAG",
        help="Tag to remove (repeatable)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.catalog import tag_simulation

    add = tuple(t.lstrip("+") for t in args.add_tags)
    remove = tuple(args.rm)
    if not add and not remove:
        print("Nothing to do: pass tags to add or --rm TAG to remove.", file=sys.stderr)
        sys.exit(2)

    workspace_root = find_catalog_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    try:
        result = tag_simulation(args.sim_ref, workspace=workspace_root, add=add, remove=remove)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except Exception as exc:  # noqa: BLE001 - map resolver errors to typed exit codes
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))

    if result["added"]:
        print(f"added: {', '.join(result['added'])}  [{result['sim_id'][:8]}]")
    if result["removed"]:
        print(f"removed: {', '.join(result['removed'])}  [{result['sim_id'][:8]}]")
    if not result["added"] and not result["removed"]:
        print("no tag change (already present / absent)")
