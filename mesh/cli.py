"""Canonical command-line interface for the standalone mesh viewer.

This module is the recommended CLI entry point. ``mesh.run_visualization`` is
kept only as a compatibility wrapper for vendored directory execution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mesh.runner.visualization_runner import (
    DEFAULT_CONFIG_FILENAME,
    DEFAULT_TOML_SECTION,
    run_visualization_from_toml,
)


def resolve_default_config_path() -> Path:
    """Return the default example TOML shipped with the package or repository."""

    mesh_dir = Path(__file__).resolve().parent
    candidates = (
        mesh_dir.parent / "examples" / "mesh_viewer" / DEFAULT_CONFIG_FILENAME,
        mesh_dir / "examples" / DEFAULT_CONFIG_FILENAME,
    )
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def build_parser() -> argparse.ArgumentParser:
    """Build the public parser for the standalone viewer."""

    default_config_path = resolve_default_config_path()
    parser = argparse.ArgumentParser(
        description=(
            "Load an exported mesh bundle, render one or more pedagogical "
            "figures, and optionally write a JSON summary."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config_path,
        help="Path to the TOML configuration file.",
    )
    parser.add_argument(
        "--section",
        type=str,
        default=DEFAULT_TOML_SECTION,
        help=f"TOML section to load (default: {DEFAULT_TOML_SECTION}).",
    )
    parser.add_argument(
        "--output-json",
        dest="output_json",
        type=Path,
        default=None,
        help="Optional path overriding the JSON summary output.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the standalone viewer from the command line.

    Use this function when embedding the CLI in another Python process. End
    users should normally call ``python -m mesh`` or
    ``python mesh/run_visualization.py``.
    """

    args = build_parser().parse_args(argv)
    summary = run_visualization_from_toml(
        args.config,
        section=args.section,
        forced_summary_output_path=args.output_json,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0


__all__ = [
    "DEFAULT_CONFIG_FILENAME",
    "DEFAULT_TOML_SECTION",
    "build_parser",
    "main",
    "resolve_default_config_path",
]
