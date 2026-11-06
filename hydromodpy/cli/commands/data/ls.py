"""``hmp data ls`` - thin wrapper around :func:`hydromodpy.list_data_cache`."""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import format_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.output import emit

NAME: str = "ls"
HELP: str = "List artifacts indexed in the workspace cache"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog="Examples:\n  hmp data ls\n  hmp data ls --variable dem --provider ign_geoplateforme_dem",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--variable", default=None, help="Filter by variable")
    parser.add_argument("--provider", default=None, help="Filter by provider")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.data import list_data_cache

    df = list_data_cache(args.workspace, variable=args.variable, provider=args.provider)
    if df is None or df.empty:

        def table_of_nothing() -> None:
            print(
                "  (no cache found)"
                if df is None
                else "  (empty cache - drop files in data/<variable>/ then run 'hmp run')"
            )

        emit(args, "data ls", [], table=table_of_nothing)
        return
    cols = [c for c in ("variable", "source", "station_id", "file_path") if c in df.columns]
    emit(args, "data ls", df, table=lambda: print(df[cols].to_string(index=False)))
