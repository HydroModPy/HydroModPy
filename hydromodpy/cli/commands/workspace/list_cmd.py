"""``hmp workspace list`` - the sealed runs of every project under a workspace.

Reads the one-row ``simulation.parquet`` each sealed run carries
(:func:`hydromodpy.results.catalog.federation.read_workspace_runs`): no index
is opened, and a project whose index was never built is listed all the same.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli._conventions import workspace_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, EXIT_OK

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
        parents=[workspace_parser()],
        epilog=(
            "Examples:\n  hmp workspace list\n  hmp workspace list ~/hydromodpy --json\n"
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
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.workspace import list_workspace_runs

    named = args.path or args.workspace
    root = Path(named).expanduser().resolve() if named else Path.cwd().resolve()
    if not root.is_dir():
        print(f"Not a directory: {root}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    df = list_workspace_runs(root)
    if df.empty:
        print(f"(no sealed run under {root})")
        sys.exit(EXIT_OK)

    columns = [c for c in _COLUMNS if c in df.columns] or list(df.columns)
    if args.json:
        print(df[columns].to_json(orient="records", date_format="iso", indent=2))
        sys.exit(EXIT_OK)
    print(df[columns].to_string(index=False))
    sys.exit(EXIT_OK)
