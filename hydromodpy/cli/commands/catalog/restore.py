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
from hydromodpy.cli.helpers import project_root_of
from hydromodpy.cli.output import emit

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
    from hydromodpy.results.catalog.indexer import reindex_if_indexed

    reindex_if_indexed(root)
    emit(
        args,
        "catalog restore",
        {"applied": True, "rel_dir": entry.rel_dir},
        table=lambda: print(f"restored {entry.rel_dir}"),
    )
