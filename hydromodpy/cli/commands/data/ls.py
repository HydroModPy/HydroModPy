"""``hmp data ls`` - thin wrapper around :func:`hydromodpy.list_data_cache`."""

from __future__ import annotations

import argparse

NAME: str = "ls"
HELP: str = "List artefacts indexed in the workspace cache"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--variable", default=None, help="Filter by variable")
    parser.add_argument("--provider", default=None, help="Filter by provider")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    import hydromodpy as hmp

    df = hmp.list_data_cache(args.workspace, variable=args.variable, provider=args.provider)
    if df is None:
        print("  (no cache found)")
        return
    if df.empty:
        print("  (empty cache - drop files in <variable>_custom/ then run 'hmp run')")
        return
    cols = [c for c in ("variable", "source", "station_id", "file_path") if c in df.columns]
    print(df[cols].to_string(index=False))
