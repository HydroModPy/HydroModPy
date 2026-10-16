"""``hmp catalog restore`` - move a trashed run or session back where it was."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli._conventions import add_sim_ref, verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import apply_verbosity, exit_code_for
from hydromodpy.core.state.paths import catalog_path_for, resolve_project_root

NAME: str = "restore"
HELP: str = "Move a trashed run or session back to the directory it came from"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), verbosity_parser()],
        epilog=(
            "Examples:\n"
            "  hmp catalog restore baseline_daily\n"
            "  hmp catalog restore runs__baseline_daily@20261014T093000"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_sim_ref(
        parser,
        help=(
            "The name 'hmp catalog trash' lists, or the directory the entry came from "
            "(baseline_daily, sessions/calibration)"
        ),
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.results.catalog.discovery import resolve_trashed
    from hydromodpy.results.trash import restore

    root = resolve_project_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    try:
        entry = resolve_trashed(root, args.sim_ref)
        restore(root, entry.name)
    except Exception as exc:  # noqa: BLE001 - map resolver and collision errors
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))
    if catalog_path_for(root).is_file():
        from hydromodpy.results.catalog.indexer import index_new_runs

        index_new_runs(root)
    print(f"restored {entry.rel_dir}")
