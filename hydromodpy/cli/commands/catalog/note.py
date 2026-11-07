"""``hmp catalog note`` - append a timestamped note to a run, in its ``annotations.json``."""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import (
    add_sim_ref,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import project_root_of
from hydromodpy.cli.output import emit

NAME: str = "note"
HELP: str = "Append a timestamped note to a run"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog='Example:\n  hmp catalog note calibration "best fit after widening Sy bounds"',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_sim_ref(parser)
    parser.add_argument(
        "--site",
        default=None,
        help="Narrow an @-selector (@last, @best:nse) to the runs of one site",
    )
    parser.add_argument("text", help="Note text")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli.auth import AuthBackend
    from hydromodpy.results.annotations import add_note
    from hydromodpy.results.catalog.discovery import resolve_rel_dir

    root = project_root_of(args)
    rel_dir = resolve_rel_dir(root, args.sim_ref, site=args.site)
    add_note(root / rel_dir, str(args.text), author=AuthBackend().current_user())
    from hydromodpy.results.catalog.indexer import reindex_if_indexed

    reindex_if_indexed(root)
    emit(
        args,
        "catalog note",
        {"rel_dir": rel_dir, "text": str(args.text)},
        table=lambda: print(f"noted [{rel_dir}]"),
    )
