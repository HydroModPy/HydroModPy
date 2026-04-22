"""``hmp worst`` — show the worst simulation for a project."""

from __future__ import annotations

import argparse

from hydromodpy._cli.commands.best import _rank_and_print

NAME = "worst"
HELP = "Show the bottom simulation for a project ranked by a metric"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("project", help="Project label")
    parser.add_argument("--metric", default="nse", help="Metric name (default: nse)")
    parser.add_argument("--workspace", default=None, help="Workspace root (default: auto-detect)")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    _rank_and_print(args, mode="worst")
