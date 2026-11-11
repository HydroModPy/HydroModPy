"""``hmp data ls`` - thin wrapper around :func:`hydromodpy.data.request.cache_verbs.list_data_cache`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.conventions import format_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.output import emit, output_of

NAME: str = "ls"
HELP: str = "List the rows of the workspace data cache"


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
    from hydromodpy.cli.refs import resolve_workspace
    from hydromodpy.data.request.cache_verbs import list_data_cache

    report = list_data_cache(
        resolve_workspace(args.workspace), variable=args.variable, provider=args.provider
    )
    if report is None:
        emit(args, "data ls", [], table=lambda: print("  (no cache found)"))
        return
    for line in report.lines():
        print(f"  {line}", file=sys.stderr)
    rows = [row.to_dict() for row in report.rows]

    def table() -> None:
        import pandas as pd

        if not rows:
            print("  (empty cache - a run records each file it fetches in the sidecar next to it)")
        else:
            frame = pd.DataFrame(
                [{**row, "path": _relative(row["path"], report.data_root)} for row in rows]
            )
            print(frame[list(output_of("data ls").fields)].fillna("").to_string(index=False))
        if report.user_files:
            print(
                f"  {len(report.user_files)} user file(s) under {report.data_root} are read in "
                "place and are not rows of the cache."
            )

    emit(args, "data ls", rows, table=table)


def _relative(path: str, data_root: Path) -> str:
    """Return *path* under the data folder when it is there, else as it is."""
    try:
        return str(Path(path).relative_to(data_root))
    except ValueError:
        return path
