"""``hmp index`` - machine-wide global index over registered workspaces.

Sub-commands:

* ``search <term>``: full-text search across registered workspace catalogs
  via the DuckDB FTS index on ``simulations.description``;
* ``forget <workspace_id>``: drop a workspace registration from the global
  index (the underlying workspace files stay untouched);
* ``prune``: remove every registration whose ``catalog.duckdb`` is no
  longer reachable on disk.

Each verb prints a human readable summary and exits ``0`` on success.
"""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_OK

NAME: str = "index"
HELP: str = "Search/forget/prune entries in the machine-wide global index"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = parser.add_subparsers(dest="index_command")

    search = sub.add_parser("search", help="Full-text search over all workspaces")
    search.add_argument("term", help="Free-form search term")
    search.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of rows to print (default: 20)",
    )

    forget = sub.add_parser("forget", help="Unregister a workspace from the global index")
    forget.add_argument("workspace_id", help="workspace_id returned by 'hmp index list'")

    sub.add_parser("prune", help="Drop registrations whose catalog.duckdb is missing")

    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    sub = getattr(args, "index_command", None)
    if sub == "search":
        _cmd_search(args)
        return
    if sub == "forget":
        _cmd_forget(args)
        return
    if sub == "prune":
        _cmd_prune(args)
        return
    print("Usage: hmp index {search|forget|prune} [options]", file=sys.stderr)
    sys.exit(EXIT_CONFIG)


def _cmd_search(args: argparse.Namespace) -> None:
    from hydromodpy.core.state.global_index import GlobalIndex

    with GlobalIndex() as gi:
        df = gi.search(args.term)
    if df is None or df.empty:
        print(f"No matches for {args.term!r}.")
        sys.exit(EXIT_OK)

    df = df.head(args.limit)
    columns = [
        c for c in ("workspace_id", "sim_id", "name", "project", "description") if c in df.columns
    ]
    if not columns:
        columns = list(df.columns)
    print(df[columns].to_string(index=False))
    sys.exit(EXIT_OK)


def _cmd_forget(args: argparse.Namespace) -> None:
    from hydromodpy.core.state.global_index import GlobalIndex

    with GlobalIndex() as gi:
        gi.forget(args.workspace_id)
    print(f"Forgot workspace {args.workspace_id}.")
    sys.exit(EXIT_OK)


def _cmd_prune(args: argparse.Namespace) -> None:
    from hydromodpy.core.state.global_index import GlobalIndex

    with GlobalIndex() as gi:
        removed = gi.prune()
    if not removed:
        print("No stale workspaces to prune.")
        sys.exit(EXIT_OK)
    print(f"Pruned {len(removed)} stale workspace(s):")
    for wid in removed:
        print(f"  - {wid}")
    sys.exit(EXIT_OK)


__all__ = ("NAME", "HELP", "register", "run")
