"""``hmp catalog import`` - restore a run from a portable ``.hmp`` archive."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli._conventions import workspace_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, exit_code_for

NAME: str = "import"
HELP: str = "Import a .hmp archive into the workspace (checksums verified first)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser()],
        epilog="Example:\n  hmp catalog import paper.hmp",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("package", help="Path to the .hmp archive")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing run with the same identity",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.catalog import import_package_run

    workspace_root = Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    try:
        result = import_package_run(args.package, workspace=workspace_root, force=args.force)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except Exception as exc:  # noqa: BLE001 - surface verification / collision errors
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))

    sids = result["sim_ids"]
    ids = ", ".join(s[:8] for s in sids)
    print(f"imported {len(sids)} run(s): {ids}")
