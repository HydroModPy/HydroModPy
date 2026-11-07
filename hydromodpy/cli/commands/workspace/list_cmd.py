"""``hmp workspace list`` - the sealed runs of every project under a workspace.

Reads the one-row ``simulation.parquet`` each sealed run carries
(:func:`hydromodpy.results.catalog.federation.read_workspace_runs`): no index
is opened, and a project whose index was never built is listed all the same.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from hydromodpy.cli.conventions import format_parser, workspace_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, refuse
from hydromodpy.cli.output import emit

NAME: str = "list"
HELP: str = "List the sealed runs of every project under a workspace, from their directories"

_COLUMNS: tuple[str, ...] = (
    "project",
    "name",
    "site",
    "solver",
    "nse",
    "created_at",
    "sim_id",
)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser()],
        epilog=(
            "Examples:\n  hmp workspace list\n  hmp workspace list ~/hydromodpy --format json\n"
            "  hmp workspace list -w ~/hydromodpy/projects/demo"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Workspace or project root (default: -w, else the current directory)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.results.catalog.federation import list_workspace_runs

    named = args.path or args.workspace
    root = Path(named).expanduser().resolve() if named else Path.cwd().resolve()
    if not root.is_dir():
        refuse(f"Not a directory: {root}", EXIT_NOT_FOUND)
    df = list_workspace_runs(root)
    columns = [column for column in _COLUMNS if column in df.columns]

    def table() -> None:
        if df.empty:
            print(f"(no sealed run under {root})")
        else:
            print(df[columns or list(df.columns)].to_string(index=False))

    emit(args, "workspace list", df, table=table)
