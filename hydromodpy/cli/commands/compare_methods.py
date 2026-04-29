"""``hmp compare-methods`` - run a TOML-driven method comparison."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_CONFIG

NAME = "compare-methods"
HELP = "Run a multi-variant method comparison from a TOML config"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("config", help="Path to method-comparison TOML config")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.analysis.comparison.orchestrator import MethodComparisonLauncher

    config_path = Path(args.config).expanduser().resolve()
    if not config_path.exists():
        print(f"Config not found: {config_path}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    manifest = MethodComparisonLauncher(config_path).run()
    manifest_path = manifest.get("manifest_path")
    if manifest_path:
        print(f"manifest: {manifest_path}")
