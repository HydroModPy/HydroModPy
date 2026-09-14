"""Small CLI-only helper for the reference 2D zone-conformal case."""

from __future__ import annotations

import argparse


def _parse_args(
    argv=None,
    *,
    default_config_file: str,
    default_section: str,
):
    parser = argparse.ArgumentParser(
        description="Generate one conformal 2D Gmsh mesh from configurable zone and river constraints."
    )
    parser.add_argument("--config-file", default=default_config_file)
    parser.add_argument("--section", default=default_section)
    parser.add_argument("--output-mesh", default=None)
    parser.add_argument("--output-summary-json", default=None)
    parser.add_argument("--output-figure", default=None)
    parser.add_argument("--output-figure-regional", default=None)
    parser.add_argument("--show-plot", action="store_true")
    return parser.parse_args(argv)


__all__ = [
    "_parse_args",
]
