"""Argument parser for the network/transient HTML report."""

from __future__ import annotations

from argparse import ArgumentParser, Namespace
from pathlib import Path


def parse_args(
    *,
    real_root: Path,
    source_transient_config: Path,
    page_title: str,
) -> Namespace:
    """Parse command-line arguments for the report builder."""
    parser = ArgumentParser(
        description="Build the MF6 network/transient calibration diagnostic HTML page."
    )
    parser.add_argument(
        "--real-root",
        type=Path,
        default=real_root,
        help="Root directory containing truth packages, score tables and run outputs.",
    )
    parser.add_argument(
        "--web-root",
        type=Path,
        default=None,
        help="Output web directory. Defaults to <real-root>/web.",
    )
    parser.add_argument(
        "--source-transient-config",
        type=Path,
        default=source_transient_config,
        help="Transient TOML config used to read recharge and source K values.",
    )
    parser.add_argument(
        "--path-base",
        type=Path,
        default=None,
        help=(
            "Base directory used to resolve relative catalog paths found in score CSVs. "
            "Defaults to the project root inferred from real-root."
        ),
    )
    parser.add_argument(
        "--page-title",
        default=page_title,
        help="Title displayed at the top of the generated HTML page.",
    )
    parser.add_argument(
        "--reference-run-root",
        type=Path,
        default=None,
        help=(
            "Run catalog used for watershed/topography/map context. Defaults to the "
            "mK=0.65 steady run under real-root."
        ),
    )
    parser.add_argument(
        "--steady-summary-csv",
        type=Path,
        default=None,
        help=(
            "CSV summary used by the didactic steady-balance figure. Defaults to "
            "<real-root>/steady_mK_network_extent_summary.csv."
        ),
    )
    parser.add_argument(
        "--truth-package",
        type=Path,
        action="append",
        default=None,
        help="Truth package candidate. Can be supplied multiple times; the first existing path is used.",
    )
    parser.add_argument(
        "--score-table",
        type=Path,
        action="append",
        default=None,
        help=(
            "Score CSV candidate. Can be supplied multiple times; the first table with "
            "completed rows is used."
        ),
    )
    return parser.parse_args()
