"""``hmp catalog restore`` - move a trashed run or session back where it was."""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import (
    add_sim_ref,
    dry_run_parser,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import apply_verbosity, project_root_of
from hydromodpy.cli.output import emit
from hydromodpy.core.state.layout import catalog_path_for

NAME: str = "restore"
HELP: str = "Move a trashed run or session back to the directory it came from"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), dry_run_parser(), format_parser(), verbosity_parser()],
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

    root = project_root_of(args)
    entry = resolve_trashed(root, args.sim_ref)
    if args.dry_run:
        emit(
            args,
            "catalog restore",
            {"applied": False, "rel_dir": entry.rel_dir},
            table=lambda: print(f"would restore {entry.rel_dir}"),
        )
        return
    restore(root, entry.name)
    if catalog_path_for(root).is_file():
        from hydromodpy.results.catalog.indexer import index_new_runs

        index_new_runs(root)
    emit(
        args,
        "catalog restore",
        {"applied": True, "rel_dir": entry.rel_dir},
        table=lambda: print(f"restored {entry.rel_dir}"),
    )
