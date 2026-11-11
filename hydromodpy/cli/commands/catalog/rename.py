"""``hmp catalog rename`` - move a run, and its session, to a new name."""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import (
    add_sim_ref,
    dry_run_parser,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.output import emit
from hydromodpy.cli.refs import project_root_of

NAME: str = "rename"
HELP: str = "Rename a run: runs/<old>/ and sessions/<old>/ move to the new name"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), dry_run_parser(), format_parser(), verbosity_parser()],
        epilog=(
            "The directory is the name, so a rename moves runs/<old>/ and, for a\n"
            "calibration, sessions/<old>/ to the new name. Links between them are ids\n"
            "and stay valid. The new name must be free: a live directory, a trashed\n"
            "one or a tombstone holding it is refused.\n"
            "\n"
            "Example:\n"
            "  hmp catalog rename baseline.v2 baseline_k2e5"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_sim_ref(parser)
    parser.add_argument(
        "--site",
        default=None,
        help="Narrow an @-selector (@last, @best:nse) to the runs of one site",
    )
    parser.add_argument("new_name", help="New directory name")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.results.catalog.discovery import resolve_rel_dir
    from hydromodpy.results.catalog.registration import rename_case

    root = project_root_of(args)
    rel_dir = resolve_rel_dir(root, args.sim_ref, site=args.site)
    renamed = rename_case(root, rel_dir, args.new_name, dry_run=args.dry_run)
    if args.dry_run:
        emit(
            args,
            "catalog rename",
            {"applied": False, "rel_dir": rel_dir, "renamed": list(renamed)},
            table=lambda: print(f"would rename {rel_dir} -> {', '.join(renamed)}"),
        )
        return
    from hydromodpy.results.catalog.indexer import reindex_if_indexed

    reindex_if_indexed(root)
    emit(
        args,
        "catalog rename",
        {"applied": True, "rel_dir": rel_dir, "renamed": list(renamed)},
        table=lambda: print(f"renamed {rel_dir} -> {', '.join(renamed)}"),
    )
