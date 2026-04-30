"""``hmp compare`` - compare two simulations side-by-side."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_NOT_FOUND, find_workspace_root

NAME: str = "compare"
HELP: str = "Compare two simulations by sim_id, prefix, or name"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("sim_a", help="First simulation")
    parser.add_argument("sim_b", help="Second simulation")
    parser.add_argument("--workspace", default=None, help="Workspace root (default: auto-detect)")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.analysis.comparison.pairwise import compare_pair
    from hydromodpy.results.catalog import (
        AmbiguousReferenceError,
        SimulationNotFoundError,
    )

    workspace_root = find_workspace_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    if not (workspace_root / "hydromodpy.duckdb").exists():
        print(f"No catalog at {workspace_root}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    try:
        df = compare_pair(args.sim_a, args.sim_b, workspace=workspace_root)
    except (AmbiguousReferenceError, SimulationNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    if df.empty:
        print("(no metrics recorded for either simulation)")
        return
    print(df.to_string())
